from datetime import datetime, timezone
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from app.config import Settings
from app.main import create_app
from app.telemetry.models import Base, TelemetrySampleRecord


def make_settings(api_key: str) -> Settings:
    return Settings(
        prometheus_url="http://prometheus:9090",
        service_keys=("orders-service",),
        collection_interval_seconds=15,
        stale_after_seconds=60,
        aggregation_window_seconds=300,
        prometheus_timeout_seconds=5,
        api_key=api_key,
        db_host="localhost",
        db_port=5432,
        db_name="test",
        db_username="test",
        db_password="test",
    )


def test_health_is_available_and_telemetry_requires_internal_key() -> None:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    app = create_app(make_settings("a" * 32), engine)

    with TestClient(app) as client:
        assert client.get("/health").json() == {"status": "UP"}
        assert client.get(
            "/api/v1/telemetry/latest/orders-service"
        ).status_code == 401
        response = client.get(
            "/api/v1/telemetry/latest/orders-service",
            headers={"X-Internal-API-Key": "a" * 32},
        )
        assert response.status_code == 404
        status = client.get(
            "/api/v1/telemetry/status",
            headers={"X-Internal-API-Key": "a" * 32},
        )
        assert status.status_code == 200
        assert status.json()["services"][0]["state"] == "idle"

    engine.dispose()


def test_latest_endpoint_returns_persisted_sample() -> None:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    now = datetime.now(timezone.utc)
    with engine.begin() as connection:
        connection.execute(
            TelemetrySampleRecord.__table__.insert().values(
                id=uuid4(),
                service_key="orders-service",
                window_start=now,
                window_seconds=15,
                incoming_rps=1,
                allowed_rps=1,
                rejected_rps=0,
                p95_latency_ms=12,
                p99_latency_ms=18,
                error_rate=0,
                cpu_utilization=None,
                memory_utilization=None,
                redis_latency_ms=None,
                queue_depth=0,
                data_quality="partial",
                collected_at=now,
            )
        )
    app = create_app(make_settings("b" * 32), engine)

    with TestClient(app) as client:
        response = client.get(
            "/api/v1/telemetry/latest/orders-service",
            headers={"X-Internal-API-Key": "b" * 32},
        )

    assert response.status_code == 200
    assert response.json()["incoming_rps"] == 1
    assert response.json()["data_quality"] == "partial"
    engine.dispose()
