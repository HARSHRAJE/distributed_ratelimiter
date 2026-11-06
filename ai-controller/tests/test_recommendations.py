from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from app.config import Settings
from app.main import create_app
from app.recommendations.recommendation_engine import RecommendationEngine
from app.recommendations.schemas import (
    RecommendationAction,
    RecommendationEvaluationInput,
)
from app.storage.repositories import RecommendationRepository
from app.telemetry.models import Base


NOW = datetime.now(timezone.utc)


def make_settings(**overrides) -> Settings:
    values = {
        "prometheus_url": "http://prometheus:9090",
        "service_keys": ("orders-service",),
        "collection_interval_seconds": 15,
        "stale_after_seconds": 60,
        "aggregation_window_seconds": 300,
        "prometheus_timeout_seconds": 5,
        "api_key": "r" * 32,
        "db_host": "localhost",
        "db_port": 5432,
        "db_name": "test",
        "db_username": "test",
        "db_password": "test",
    }
    values.update(overrides)
    return Settings(**values)


def make_inputs(**overrides) -> RecommendationEvaluationInput:
    values = {
        "current_rate": 200,
        "min_refill_rate": 50,
        "max_refill_rate": 500,
        "hard_max_refill_rate": 600,
        "safe_capacity_rps": 400,
        "forecast_rps": 300,
        "forecast_confidence": 0.9,
        "policy_version": 7,
        "telemetry_timestamp": NOW,
        "cpu_utilization": 50,
        "p95_latency_ms": 100,
        "p99_latency_ms": 200,
        "error_rate": 0.1,
        "queue_depth": 10,
    }
    values.update(overrides)
    return RecommendationEvaluationInput(**values)


@pytest.mark.parametrize(
    ("input_changes", "expected_action"),
    [
        (
            {"telemetry_timestamp": NOW - timedelta(seconds=61)},
            RecommendationAction.HOLD,
        ),
        ({"forecast_confidence": 0.2}, RecommendationAction.HOLD),
        ({"cpu_utilization": 90}, RecommendationAction.DECREASE),
        ({"p95_latency_ms": 600}, RecommendationAction.DECREASE),
        ({"p99_latency_ms": 1100}, RecommendationAction.DECREASE),
        ({"error_rate": 6}, RecommendationAction.DECREASE),
        ({}, RecommendationAction.INCREASE),
    ],
)
def test_deterministic_recommendation_rules(
    input_changes,
    expected_action,
) -> None:
    action, _, _ = RecommendationEngine(make_settings()).recommend(
        make_inputs(**input_changes),
        now=NOW,
        cooldown_active=False,
    )

    assert action == expected_action


def test_safety_bounds_hard_max_minimum_and_change_percent() -> None:
    engine = RecommendationEngine(
        make_settings(max_change_percent=10, cooldown_seconds=0)
    )
    increase, increased_rate, _ = engine.recommend(
        make_inputs(
            current_rate=200,
            safe_capacity_rps=1000,
            max_refill_rate=1000,
            hard_max_refill_rate=210,
        ),
        now=NOW,
        cooldown_active=False,
    )
    assert increase == RecommendationAction.INCREASE
    assert increased_rate == pytest.approx(210)

    decrease, decreased_rate, _ = engine.recommend(
        make_inputs(
            current_rate=200,
            min_refill_rate=195,
            cpu_utilization=99,
        ),
        now=NOW,
        cooldown_active=False,
    )
    assert decrease == RecommendationAction.DECREASE
    assert decreased_rate >= 195
    assert decreased_rate >= 180
    assert 200 - decreased_rate <= 20


def test_demand_above_capacity_does_not_reduce_an_already_safe_limit() -> None:
    action, rate, _ = RecommendationEngine(make_settings()).recommend(
        make_inputs(forecast_rps=500, current_rate=200, safe_capacity_rps=250),
        now=NOW,
        cooldown_active=False,
    )

    assert action == RecommendationAction.HOLD
    assert rate == 200


def test_cooldown_holds_repeated_non_emergency_recommendation() -> None:
    action, rate, reason = RecommendationEngine(make_settings()).recommend(
        make_inputs(),
        now=NOW,
        cooldown_active=True,
    )

    assert action == RecommendationAction.HOLD
    assert rate == 200
    assert "Cooldown" in reason


def create_client():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    app = create_app(make_settings(), engine)
    return engine, TestClient(app)


def test_recommendation_api_persists_global_records_and_requires_auth() -> None:
    engine, client = create_client()
    payload = make_inputs().model_dump(mode="json")
    headers = {"X-Internal-API-Key": "r" * 32}

    assert client.post(
        "/api/v1/recommendations/evaluate/orders-service",
        json=payload,
    ).status_code == 401
    response = client.post(
        "/api/v1/recommendations/evaluate/orders-service",
        headers=headers,
        json=payload,
    )
    assert response.status_code == 200, response.text
    recommendation = response.json()
    assert recommendation["scope"] == "GLOBAL"
    assert recommendation["action"] == "INCREASE"
    assert recommendation["status"] == "PENDING"
    recommendation_id = recommendation["id"]

    assert client.get(
        "/api/v1/recommendations/orders-service/latest",
        headers=headers,
    ).json()["id"] == recommendation_id
    assert client.get(
        "/api/v1/recommendations/orders-service/history",
        headers=headers,
    ).json()["recommendations"][0]["id"] == recommendation_id
    engine.dispose()
    client.close()


def test_expired_and_outdated_recommendations_cannot_be_accepted() -> None:
    engine, client = create_client()
    headers = {"X-Internal-API-Key": "r" * 32}
    payload = make_inputs().model_dump(mode="json")
    created = client.post(
        "/api/v1/recommendations/evaluate/orders-service",
        headers=headers,
        json=payload,
    ).json()

    expired_id = uuid4()
    with client.app.state.session_factory() as session:
        RecommendationRepository(session).create(
            id=expired_id,
            service_key="orders-service",
            scope="GLOBAL",
            current_rate=200,
            recommended_rate=220,
            action="INCREASE",
            reason="expired test record",
            forecast_rps=300,
            forecast_confidence=0.9,
            safe_capacity_rps=400,
            policy_version=7,
            generated_at=NOW - timedelta(minutes=10),
            expires_at=NOW - timedelta(minutes=5),
        )

    expired = client.patch(
        f"/api/v1/recommendations/{expired_id}/accept",
        headers=headers,
        json={"current_policy_version": 7},
    )
    assert expired.status_code == 409
    with client.app.state.session_factory() as session:
        assert RecommendationRepository(session).get(expired_id).status == "EXPIRED"

    outdated = client.patch(
        f"/api/v1/recommendations/{created['id']}/accept",
        headers=headers,
        json={"current_policy_version": 8},
    )
    assert outdated.status_code == 409
    with client.app.state.session_factory() as session:
        assert (
            RecommendationRepository(session).get(UUID(created["id"])).status
            == "PENDING"
        )

    accepted = client.patch(
        f"/api/v1/recommendations/{created['id']}/accept",
        headers=headers,
        json={"current_policy_version": 7},
    )
    assert accepted.status_code == 200
    assert accepted.json()["status"] == "ACCEPTED"
    engine.dispose()
    client.close()
