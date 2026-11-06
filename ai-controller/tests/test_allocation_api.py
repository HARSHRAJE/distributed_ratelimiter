from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from app.config import Settings
from app.main import create_app
from app.telemetry.models import Base


def test_allocation_configuration_and_evaluation_api():
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
        api_key="i" * 32,
        db_host="localhost",
        db_port=5432,
        db_name="test",
        db_username="test",
        db_password="test",
    )
    client = TestClient(create_app(settings, engine))
    headers = {"X-Internal-API-Key": "i" * 32}

    configured = client.put(
        "/api/v1/allocations/orders-service/tenants",
        headers=headers,
        json={
            "tenants": [
                {
                    "tenant_id": "tenant-a",
                    "tenant_priority": 1,
                    "weight": "3",
                    "minimum_rate": "0",
                    "maximum_rate": "1000",
                    "predicted_demand": "1000",
                    "current_allocation": "0",
                },
                {
                    "tenant_id": "tenant-b",
                    "tenant_priority": 1,
                    "weight": "1",
                    "minimum_rate": "0",
                    "maximum_rate": "1000",
                    "predicted_demand": "1000",
                    "current_allocation": "0",
                },
            ]
        },
    )
    assert configured.status_code == 200

    evaluated = client.post(
        "/api/v1/allocations/evaluate/orders-service",
        headers=headers,
        json={"global_capacity_rps": "100"},
    )
    assert evaluated.status_code == 200
    body = evaluated.json()
    assert body["allocation_version"] == 1
    assert body["allocations"][0]["allocation_rate"] == "75.000"
    assert body["allocations"][1]["allocation_rate"] == "25.000"
    assert float(body["metrics"]["global_capacity_utilization"]) == 1

    latest = client.get(
        "/api/v1/allocations/orders-service/latest",
        headers=headers,
    )
    assert latest.status_code == 200
    assert latest.json()["allocation_run_id"] == body["allocation_run_id"]

    history = client.get(
        "/api/v1/allocations/orders-service/history",
        headers=headers,
    )
    assert history.status_code == 200
    assert len(history.json()["runs"]) == 1


def test_allocation_api_rejects_minimums_above_safe_capacity():
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
        api_key="i" * 32,
        db_host="localhost",
        db_port=5432,
        db_name="test",
        db_username="test",
        db_password="test",
    )
    client = TestClient(create_app(settings, engine))
    headers = {"X-Internal-API-Key": "i" * 32}

    response = client.put(
        "/api/v1/allocations/orders-service/tenants",
        headers=headers,
        json={
            "tenants": [
                {
                    "tenant_id": "tenant-a",
                    "weight": "1",
                    "minimum_rate": "60",
                    "maximum_rate": "100",
                    "predicted_demand": "100",
                    "current_allocation": "60",
                },
                {
                    "tenant_id": "tenant-b",
                    "weight": "1",
                    "minimum_rate": "60",
                    "maximum_rate": "100",
                    "predicted_demand": "100",
                    "current_allocation": "60",
                },
            ]
        },
    )
    assert response.status_code == 200

    response = client.post(
        "/api/v1/allocations/evaluate/orders-service",
        headers=headers,
        json={"global_capacity_rps": "100"},
    )
    assert response.status_code == 422
    assert "minimum allocations exceeds" in response.json()["detail"]
