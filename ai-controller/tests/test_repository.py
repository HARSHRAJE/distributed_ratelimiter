from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.storage.repositories import TelemetryRepository
from app.telemetry.collector import CollectedTelemetry
from app.telemetry.models import Base, TelemetrySampleRecord


def test_duplicate_sample_window_is_ignored() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    collected_at = datetime.now(timezone.utc)
    sample = CollectedTelemetry(
        id=uuid4(),
        service_key="orders-service",
        timestamp=collected_at,
        window_seconds=15,
        incoming_rps=3,
        allowed_rps=2,
        rejected_rps=1,
        p95_latency_ms=10,
        p99_latency_ms=20,
        error_rate=0,
        cpu_utilization=None,
        memory_utilization=None,
        redis_latency_ms=None,
        queue_depth=None,
        data_quality="partial",
        collected_at=collected_at,
    )

    with Session(engine) as session:
        repository = TelemetryRepository(session)
        assert repository.save_sample(sample) is True
        assert repository.save_sample(sample) is False
        rows = session.scalars(select(TelemetrySampleRecord)).all()
        assert len(rows) == 1

    engine.dispose()
