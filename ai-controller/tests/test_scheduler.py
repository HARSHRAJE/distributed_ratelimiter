import asyncio
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import create_engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.config import Settings
from app.scheduler.collection_scheduler import collect_cycle
from app.storage.repositories import TelemetryRepository
from app.telemetry.aggregator import TelemetryAggregator
from app.telemetry.collector import CollectedTelemetry
from app.telemetry.models import Base
import app.scheduler.collection_scheduler as scheduler


class UnavailableCollector:
    async def collect(self, service_key: str, *, now=None):
        raise RuntimeError("Prometheus unavailable")


def test_collection_failure_is_recorded_for_retry_visibility() -> None:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    settings = Settings(
        prometheus_url="http://prometheus:9090",
        service_keys=("orders-service",),
        collection_interval_seconds=15,
        stale_after_seconds=60,
        aggregation_window_seconds=300,
        prometheus_timeout_seconds=5,
        api_key="x" * 32,
        db_host="localhost",
        db_port=5432,
        db_name="test",
        db_username="test",
        db_password="test",
    )

    asyncio.run(
        collect_cycle(
            settings,
            engine,
            UnavailableCollector(),
            TelemetryAggregator(),
            now=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
    )

    with Session(engine) as session:
        statuses = TelemetryRepository(session).collection_status()
    assert len(statuses) == 1
    assert statuses[0].state == "failed"
    assert statuses[0].last_error == "RuntimeError"
    engine.dispose()


def test_postgres_outage_retries_same_collected_window(monkeypatch) -> None:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    settings = Settings(
        prometheus_url="http://prometheus:9090",
        service_keys=("orders-service",),
        collection_interval_seconds=15,
        stale_after_seconds=60,
        aggregation_window_seconds=300,
        prometheus_timeout_seconds=5,
        api_key="x" * 32,
        db_host="localhost",
        db_port=5432,
        db_name="test",
        db_username="test",
        db_password="test",
    )
    collected_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    sample = CollectedTelemetry(
        id=uuid4(),
        service_key="orders-service",
        timestamp=collected_at,
        window_seconds=15,
        incoming_rps=10,
        allowed_rps=8,
        rejected_rps=2,
        p95_latency_ms=25,
        p99_latency_ms=40,
        error_rate=0,
        cpu_utilization=None,
        memory_utilization=None,
        redis_latency_ms=None,
        queue_depth=None,
        data_quality="partial",
        collected_at=collected_at,
    )

    class FixedCollector:
        calls = 0

        async def collect(self, service_key: str, *, now=None):
            self.calls += 1
            return sample

    original_save = TelemetryRepository.save_sample
    save_attempts = 0

    def fail_once(repository, collected_sample):
        nonlocal save_attempts
        save_attempts += 1
        if save_attempts == 1:
            raise OperationalError("insert", {}, RuntimeError("offline"))
        return original_save(repository, collected_sample)

    async def no_wait(_: float) -> None:
        return None

    monkeypatch.setattr(TelemetryRepository, "save_sample", fail_once)
    monkeypatch.setattr(scheduler.asyncio, "sleep", no_wait)
    collector = FixedCollector()

    asyncio.run(
        scheduler.collect_cycle(
            settings,
            engine,
            collector,
            TelemetryAggregator(),
            now=collected_at,
        )
    )

    with Session(engine) as session:
        repository = TelemetryRepository(session)
        records = repository.history("orders-service", limit=10)
        statuses = repository.collection_status()
    assert collector.calls == 1
    assert save_attempts == 2
    assert len(records) == 1
    assert statuses[0].state == "success"
    engine.dispose()
