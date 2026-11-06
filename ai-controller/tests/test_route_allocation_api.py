from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from app.config import Settings
from app.main import create_app
from app.telemetry.models import Base


def test_route_allocation_api_is_shadow_only_and_supports_comparison():
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

    tenant_configs = client.put(
        "/api/v1/allocations/orders-service/tenants",
        headers=headers,
        json={
            "tenants": [
                {
                    "tenant_id": "tenant-a",
                    "tenant_priority": 1,
                    "weight": "1",
                    "minimum_rate": "0",
                    "maximum_rate": "100",
                    "predicted_demand": "100",
                    "current_allocation": "0",
                }
            ]
        },
    )
    assert tenant_configs.status_code == 200
    tenant_run = client.post(
        "/api/v1/allocations/evaluate/orders-service",
        headers=headers,
        json={"global_capacity_rps": "100"},
    )
    assert tenant_run.status_code == 200

    route_configs = client.put(
        "/api/v1/allocation/routes/orders-service/configs",
        headers=headers,
        json={
            "routes": [
                {
                    "tenant_id": "tenant-a",
                    "route_id": "route-one",
                    "route_weight": "1",
                    "route_minimum_rate": "0",
                    "route_maximum_rate": "100",
                    "resource_cost_factor": "1",
                    "predicted_demand": "100",
                },
                {
                    "tenant_id": "tenant-a",
                    "route_id": "route-two",
                    "route_weight": "1",
                    "route_minimum_rate": "0",
                    "route_maximum_rate": "100",
                    "resource_cost_factor": "2",
                    "predicted_demand": "100",
                },
            ]
        },
    )
    assert route_configs.status_code == 200

    for _ in range(2):
        evaluation = client.post(
            "/api/v1/allocation/routes/orders-service/evaluate",
            headers=headers,
            json={"backend_resource_budget": "60"},
        )
        assert evaluation.status_code == 200
        assert sum(
            float(item["allocated_rate"])
            for item in evaluation.json()["allocations"]
        ) <= 100
        assert float(
            evaluation.json()["metrics"]["estimated_resource_usage"]
        ) <= 60

    latest = client.get(
        "/api/v1/allocation/routes/orders-service",
        headers=headers,
    )
    assert latest.status_code == 200
    assert latest.json()["allocation_version"] == 2

    history = client.get(
        "/api/v1/allocation/routes/orders-service/history",
        headers=headers,
    )
    assert history.status_code == 200
    assert len(history.json()["runs"]) == 2

    comparison = client.get(
        "/api/v1/allocation/routes/orders-service/comparison",
        headers=headers,
    )
    assert comparison.status_code == 200
    assert comparison.json()["proposed_allocation_run_id"] == (
        latest.json()["allocation_run_id"]
    )


def test_route_allocation_fails_closed_without_tenant_allocation():
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
    response = client.post(
        "/api/v1/allocation/routes/orders-service/evaluate",
        headers={"X-Internal-API-Key": "i" * 32},
        json={"backend_resource_budget": "10"},
    )

    assert response.status_code == 422
    assert "tenant allocation run is required" in response.json()["detail"]
