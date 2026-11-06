from datetime import datetime, timedelta, timezone
from uuid import uuid4

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool

from app.config import Settings
from app.main import create_app
from app.safety.schemas import ValidationStatus
from app.shadow.schemas import (
    BucketConfiguration,
    ShadowEvaluationRequest,
    StrategyName,
    TrafficPoint,
)
from app.shadow.shadow_repository import ShadowRepository
from app.shadow.shadow_service import ShadowEvaluationError, ShadowService
from app.shadow.traffic_simulator import TokenBucket, simulate_token_buckets
from app.storage.repositories import RecommendationValidationRepository
from app.telemetry.models import (
    Base,
    PolicyRecommendationRecord,
    TelemetrySampleRecord,
)


NOW = datetime.now(timezone.utc)


def make_settings() -> Settings:
    return Settings(
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


def point(
    *,
    start: datetime = NOW,
    duration: int = 1,
    incoming: float,
) -> TrafficPoint:
    return TrafficPoint(
        timestamp=start,
        window_seconds=duration,
        incoming_rps=incoming,
    )


def simulate(
    points: list[TrafficPoint],
    *,
    global_capacity: int = 100,
    global_rate: float = 100,
    tenant_capacity: int = 100,
    tenant_rate: float = 100,
    route_capacity: int = 100,
    route_rate: float = 100,
):
    return simulate_token_buckets(
        points,
        global_bucket=TokenBucket(global_capacity, global_rate),
        tenant_bucket=BucketConfiguration(
            capacity=tenant_capacity,
            refill_rate_rps=tenant_rate,
        ),
        route_bucket=BucketConfiguration(
            capacity=route_capacity,
            refill_rate_rps=route_rate,
        ),
    )


def test_normal_traffic_is_admitted_by_all_buckets() -> None:
    result = simulate([point(incoming=5)])

    assert result.admitted_requests == 5
    assert result.rejected_requests == 0


def test_burst_is_limited_by_initial_token_capacity() -> None:
    result = simulate(
        [point(incoming=20)],
        global_capacity=3,
        global_rate=1,
    )

    assert result.admitted_requests == 3
    assert result.rejected_requests == 17


def test_spike_consumes_burst_then_bucket_recovers_with_elapsed_time() -> None:
    result = simulate(
        [
            point(start=NOW, incoming=0),
            point(start=NOW + timedelta(seconds=1), incoming=20),
            point(start=NOW + timedelta(seconds=2), incoming=0),
            point(start=NOW + timedelta(seconds=3), incoming=1),
        ],
        global_capacity=3,
        global_rate=1,
    )

    assert result.admitted_requests == 4
    assert result.rejected_requests == 17


def test_sustained_overload_refills_tokens_over_elapsed_time() -> None:
    result = simulate(
        [point(start=NOW + timedelta(seconds=index), incoming=10) for index in range(4)],
        global_capacity=2,
        global_rate=1,
    )

    assert result.admitted_requests == 5
    assert result.rejected_requests == 35


@pytest.mark.parametrize(
    ("bucket_values", "expected_admitted"),
    [
        ({"tenant_capacity": 2, "tenant_rate": 0.1}, 2),
        ({"route_capacity": 1, "route_rate": 0.1}, 1),
        ({"global_capacity": 2, "global_rate": 0.1}, 2),
    ],
)
def test_each_bucket_constraint_can_limit_admission(
    bucket_values,
    expected_admitted,
) -> None:
    result = simulate([point(incoming=10)], **bucket_values)

    assert result.admitted_requests == expected_admitted
    assert result.admitted_requests + result.rejected_requests == 10


def make_app():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    service_id = str(uuid4())
    policy_id = str(uuid4())
    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE services ("
                "id TEXT PRIMARY KEY, service_key TEXT, global_capacity INTEGER, "
                "global_refill_rate NUMERIC, config_version INTEGER, "
                "hard_max_refill_rate NUMERIC, adaptive_enabled BOOLEAN)"
            )
        )
        connection.execute(
            text(
                "CREATE TABLE rate_limit_policies ("
                "id TEXT PRIMARY KEY, service_id TEXT, tenant_id TEXT, "
                "route_id TEXT, active_version INTEGER, status TEXT)"
            )
        )
        connection.execute(
            text(
                "CREATE TABLE rate_limit_policy_versions ("
                "policy_id TEXT, version INTEGER, tenant_capacity INTEGER, "
                "tenant_refill_rate NUMERIC, route_capacity INTEGER, "
                "route_refill_rate NUMERIC, min_refill_rate NUMERIC)"
            )
        )
        connection.execute(
            text(
                "INSERT INTO services VALUES "
                "(:id, 'orders-service', 100, 10, 3, 100, 1)"
            ),
            {"id": service_id},
        )
        connection.execute(
            text(
                "INSERT INTO rate_limit_policies VALUES "
                "(:id, :service_id, 'tenant-a', 'route-a', 1, 'ACTIVE')"
            ),
            {"id": policy_id, "service_id": service_id},
        )
        connection.execute(
            text(
                "INSERT INTO rate_limit_policy_versions VALUES "
                "(:policy_id, 1, 100, 20, 100, 20, 1)"
            ),
            {"policy_id": policy_id},
        )
    app = create_app(make_settings(), engine)
    recommendation_id = uuid4()
    with app.state.session_factory() as session:
        recommendation = PolicyRecommendationRecord(
            id=recommendation_id,
            service_key="orders-service",
            scope="GLOBAL",
            current_rate=10,
            recommended_rate=11,
            action="INCREASE",
            reason="healthy backend",
            forecast_rps=8,
            forecast_confidence=0.9,
            safe_capacity_rps=20,
            policy_version=3,
            status="PENDING",
            generated_at=NOW - timedelta(seconds=30),
            expires_at=NOW + timedelta(minutes=5),
        )
        session.add(recommendation)
        session.commit()
        RecommendationValidationRepository(session).create(
            validation_id=uuid4(),
            recommendation_id=recommendation_id,
            status=ValidationStatus.VALID.value,
            validation_result={"status": "VALID", "checks": []},
            validated_at=NOW - timedelta(seconds=20),
            validator_version="1.0",
        )
        for index in range(6):
            start = NOW - timedelta(seconds=90 - index * 15)
            session.add(
                TelemetrySampleRecord(
                    id=uuid4(),
                    service_key="orders-service",
                    window_start=start,
                    window_seconds=15,
                    incoming_rps=8,
                    allowed_rps=8,
                    rejected_rps=0,
                    p95_latency_ms=25,
                    p99_latency_ms=50,
                    error_rate=0,
                    cpu_utilization=30,
                    memory_utilization=50,
                    redis_latency_ms=1,
                    queue_depth=0,
                    data_quality="valid",
                    collected_at=start + timedelta(seconds=1),
                )
            )
        session.commit()
    return engine, app, recommendation_id


def test_shadow_api_replays_real_telemetry_and_compares_three_strategies() -> None:
    engine, app, recommendation_id = make_app()
    headers = {"X-Internal-API-Key": "x" * 32}
    payload = {
        "recommendation_id": str(recommendation_id),
        "safe_capacity_rps": 20,
        "evaluation_window_seconds": 90,
        "tenant_key": "tenant-a",
        "route_key": "route-a",
        "rule_based_rate": 11,
    }

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/shadow/evaluate/orders-service",
            headers=headers,
            json=payload,
        )
        assert response.status_code == 200, response.text
        result = response.json()
        assert result["actual_incoming_rps"] == pytest.approx(8)
        assert result["evaluation_window_seconds"] == 75
        assert {
            outcome["strategy"] for outcome in result["strategies"]
        } == {strategy.value for strategy in StrategyName}
        assert result["input_metadata"]["bucket_configuration"]["tenant"]["key"] == "tenant-a"
        with app.state.session_factory() as session:
            recommendation = session.get(
                PolicyRecommendationRecord,
                recommendation_id,
            )
            assert recommendation.status == "PENDING"
            assert recommendation.recommended_rate == 11

        latest = client.get(
            "/api/v1/shadow/orders-service/latest",
            headers=headers,
        )
        history = client.get(
            "/api/v1/shadow/orders-service/history",
            headers=headers,
        )
        comparison = client.get(
            "/api/v1/shadow/orders-service/comparison",
            headers=headers,
        )
        assert latest.status_code == 200
        assert len(history.json()["evaluations"]) == 1
        assert {
            item["strategy"] for item in comparison.json()["strategies"]
        } == {strategy.value for strategy in StrategyName}
    engine.dispose()


def test_shadow_service_rejects_recommendation_without_valid_safety_record() -> None:
    engine, app, recommendation_id = make_app()
    with app.state.session_factory() as session:
        repository = ShadowRepository(session)
        validation = repository.latest_validation(recommendation_id)
        validation.status = "REJECTED"
        session.commit()
        service = ShadowService(make_settings())
        request = ShadowEvaluationRequest(
            recommendation_id=recommendation_id,
            safe_capacity_rps=20,
            evaluation_window_seconds=90,
            tenant_key="tenant-a",
            route_key="route-a",
            rule_based_rate=11,
        )
        with pytest.raises(ShadowEvaluationError, match="passing safety"):
            service.evaluate(
                "orders-service",
                request,
                repository,
                now=NOW,
            )
    engine.dispose()


def test_shadow_uses_live_policy_version_and_adaptive_status() -> None:
    engine, app, recommendation_id = make_app()
    request = ShadowEvaluationRequest(
        recommendation_id=recommendation_id,
        safe_capacity_rps=20,
        evaluation_window_seconds=60,
        tenant_key="tenant-a",
        route_key="route-a",
        rule_based_rate=11,
    )
    with app.state.session_factory() as session:
        repository = ShadowRepository(session)
        service = ShadowService(make_settings())
        session.execute(text("UPDATE services SET config_version = 4"))
        session.commit()
        with pytest.raises(ShadowEvaluationError, match="outdated"):
            service.evaluate(
                "orders-service",
                request,
                repository,
                now=NOW,
            )

        session.execute(
            text(
                "UPDATE services SET config_version = 3, adaptive_enabled = 0"
            )
        )
        session.commit()
        with pytest.raises(ShadowEvaluationError, match="not enabled"):
            service.evaluate(
                "orders-service",
                request,
                repository,
                now=NOW,
            )
    engine.dispose()
