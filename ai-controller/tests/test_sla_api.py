from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from app.config import Settings
from app.main import create_app
from app.telemetry.models import Base


def test_sla_endpoints_store_tier_defaults_and_mark_compliance_unmeasurable():
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

    created = client.put(
        "/api/v1/sla/orders-service/tenants",
        headers=headers,
        json={
            "tenants": [
                {"tenant_id": "basic", "tier": "BASIC", "predicted_demand": 1000},
                {"tenant_id": "pro", "tier": "PRO", "predicted_demand": 1000},
                {
                    "tenant_id": "enterprise",
                    "tier": "ENTERPRISE",
                    "predicted_demand": 1000,
                },
            ]
        },
    )
    assert created.status_code == 200
    assert [
        (
            item["priority"],
            float(item["allocation_weight"]),
            float(item["minimum_guaranteed_rate"]),
            float(item["maximum_rate"]),
        )
        for item in created.json()
    ] == [
        (1, 1, 50, 150),
        (2, 2, 100, 400),
        (3, 4, 200, 800),
    ]

    evaluated = client.post(
        "/api/v1/sla/orders-service/evaluate",
        headers=headers,
        json={"global_service_capacity": "1000"},
    )
    assert evaluated.status_code == 200
    run = evaluated.json()
    assert run["allocation_version"] == 1
    assert sum(float(item["allocated_rate"]) for item in run["allocations"]) == 1000

    listed = client.get(
        "/api/v1/sla/orders-service/tenants",
        headers=headers,
    )
    assert listed.status_code == 200
    single = client.get(
        "/api/v1/sla/orders-service/tenants/pro",
        headers=headers,
    )
    assert single.status_code == 200
    assert single.json()["config_version"] == 1

    compliance = client.get(
        "/api/v1/sla/orders-service/compliance",
        headers=headers,
    )
    assert compliance.status_code == 200
    assert all(
        item["sla_compliance"] == "NOT_MEASURABLE"
        for item in compliance.json()["tenants"]
    )

    history = client.get(
        "/api/v1/sla/orders-service/allocation-history",
        headers=headers,
    )
    assert history.status_code == 200
    assert history.json()["runs"][0]["allocation_run_id"] == (
        run["allocation_run_id"]
    )


def test_sla_evaluation_rejects_impossible_guarantees():
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
        "/api/v1/sla/orders-service/tenants",
        headers=headers,
        json={
            "tenants": [
                {
                    "tenant_id": "basic",
                    "tier": "BASIC",
                    "minimum_guaranteed_rate": "60",
                    "maximum_rate": "100",
                },
                {
                    "tenant_id": "pro",
                    "tier": "BASIC",
                    "minimum_guaranteed_rate": "60",
                    "maximum_rate": "100",
                },
            ]
        },
    )
    assert configured.status_code == 200
    response = client.post(
        "/api/v1/sla/orders-service/evaluate",
        headers=headers,
        json={"global_service_capacity": "100"},
    )
    assert response.status_code == 422
    assert "exceed global service capacity" in response.json()["detail"]
