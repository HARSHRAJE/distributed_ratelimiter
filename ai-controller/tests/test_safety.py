from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from app.config import Settings
from app.main import create_app
from app.recommendations.schemas import (
    RecommendationAction,
    RecommendationRecordSchema,
    RecommendationStatus,
)
from app.safety.safety_validator import SafetyValidator
from app.safety.schemas import ValidationContext, ValidationRule, ValidationStatus
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
        "api_key": "s" * 32,
        "db_host": "localhost",
        "db_port": 5432,
        "db_name": "test",
        "db_username": "test",
        "db_password": "test",
    }
    values.update(overrides)
    return Settings(**values)


def make_recommendation(**overrides) -> RecommendationRecordSchema:
    values = {
        "id": uuid4(),
        "service_key": "orders-service",
        "scope": "GLOBAL",
        "current_rate": 200,
        "recommended_rate": 220,
        "action": RecommendationAction.INCREASE,
        "reason": "Backend is healthy and global rate is below safe capacity",
        "forecast_rps": 300,
        "forecast_confidence": 0.9,
        "safe_capacity_rps": 400,
        "policy_version": 7,
        "status": RecommendationStatus.PENDING,
        "generated_at": NOW - timedelta(seconds=1),
        "expires_at": NOW + timedelta(minutes=5),
    }
    values.update(overrides)
    return RecommendationRecordSchema(**values)


def make_context(**overrides) -> ValidationContext:
    values = {
        "current_rate": 200,
        "min_refill_rate": 50,
        "hard_max_refill_rate": 600,
        "current_policy_version": 7,
        "telemetry_timestamp": NOW,
        "adaptive_control_enabled": True,
        "safe_capacity_rps": 400,
    }
    values.update(overrides)
    return ValidationContext(**values)


def validate(
    recommendation: RecommendationRecordSchema | None = None,
    context: ValidationContext | None = None,
    *,
    cooldown_active: bool = False,
    settings: Settings | None = None,
):
    return SafetyValidator(settings or make_settings()).validate(
        recommendation or make_recommendation(),
        context or make_context(),
        cooldown_active=cooldown_active,
        now=NOW,
    )


def test_valid_recommendation_passes_all_checks() -> None:
    result = validate()

    assert result.status == ValidationStatus.VALID
    assert all(check.passed for check in result.checks)
    assert result.recommendation_id


@pytest.mark.parametrize(
    ("recommendation_changes", "context_changes", "extra", "failed_rule"),
    [
        (
            {"recommended_rate": 230},
            {"hard_max_refill_rate": 225},
            {},
            ValidationRule.HARD_MAX_RATE,
        ),
        (
            {"recommended_rate": 40},
            {},
            {},
            ValidationRule.MINIMUM_RATE,
        ),
        (
            {"recommended_rate": 225},
            {},
            {},
            ValidationRule.MAX_CHANGE_PERCENT,
        ),
        (
            {},
            {"current_policy_version": 8},
            {},
            ValidationRule.POLICY_VERSION,
        ),
        (
            {"expires_at": NOW - timedelta(seconds=1)},
            {},
            {},
            ValidationRule.EXPIRATION,
        ),
        (
            {},
            {"telemetry_timestamp": NOW - timedelta(seconds=61)},
            {},
            ValidationRule.TELEMETRY_FRESHNESS,
        ),
        (
            {"forecast_confidence": 0.4},
            {},
            {},
            ValidationRule.FORECAST_CONFIDENCE,
        ),
        (
            {},
            {},
            {"cooldown_active": True},
            ValidationRule.COOLDOWN,
        ),
        (
            {},
            {"adaptive_control_enabled": False},
            {},
            ValidationRule.SERVICE_STATUS,
        ),
        (
            {},
            {"safe_capacity_rps": 210},
            {},
            ValidationRule.SAFE_CAPACITY,
        ),
    ],
)
def test_safety_rules_report_each_failure(
    recommendation_changes,
    context_changes,
    extra,
    failed_rule,
) -> None:
    cooldown_active = extra.get("cooldown_active", False)
    result = validate(
        make_recommendation(**recommendation_changes),
        make_context(**context_changes),
        cooldown_active=cooldown_active,
    )

    assert result.status == ValidationStatus.REJECTED
    assert failed_rule in {
        check.rule for check in result.checks if not check.passed
    }


def test_multiple_validation_failures_are_reported_together() -> None:
    result = validate(
        make_recommendation(
            recommended_rate=250,
            forecast_confidence=0.4,
            expires_at=NOW - timedelta(seconds=1),
        ),
        make_context(
            min_refill_rate=260,
            hard_max_refill_rate=240,
            current_policy_version=8,
            telemetry_timestamp=NOW - timedelta(seconds=61),
            adaptive_control_enabled=False,
            safe_capacity_rps=220,
        ),
        cooldown_active=True,
    )

    failed_rules = {check.rule for check in result.checks if not check.passed}
    assert result.status == ValidationStatus.REJECTED
    assert {
        ValidationRule.HARD_MAX_RATE,
        ValidationRule.MINIMUM_RATE,
        ValidationRule.MAX_CHANGE_PERCENT,
        ValidationRule.POLICY_VERSION,
        ValidationRule.EXPIRATION,
        ValidationRule.TELEMETRY_FRESHNESS,
        ValidationRule.FORECAST_CONFIDENCE,
        ValidationRule.COOLDOWN,
        ValidationRule.SERVICE_STATUS,
        ValidationRule.SAFE_CAPACITY,
    }.issubset(failed_rules)


def test_validation_api_persists_each_attempt_and_serves_history() -> None:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    app = create_app(make_settings(), engine)
    headers = {"X-Internal-API-Key": "s" * 32}
    with app.state.session_factory() as session:
        recommendation = RecommendationRepository(session).create(
            service_key="orders-service",
            scope="GLOBAL",
            current_rate=200,
            recommended_rate=220,
            action="INCREASE",
            reason="healthy backend",
            forecast_rps=300,
            forecast_confidence=0.9,
            safe_capacity_rps=400,
            policy_version=7,
            generated_at=NOW - timedelta(seconds=1),
            expires_at=NOW + timedelta(minutes=5),
        )
        recommendation_id = recommendation.id

    context = make_context().model_dump(mode="json")
    with TestClient(app) as client:
        endpoint = f"/api/v1/safety/validate/{recommendation_id}"
        assert client.post(endpoint, json=context).status_code == 401
        first = client.post(endpoint, headers=headers, json=context)
        second = client.post(endpoint, headers=headers, json=context)
        assert first.status_code == 200, first.text
        assert second.status_code == 200, second.text
        assert first.json()["status"] == "VALID"
        assert first.json()["id"] != second.json()["id"]

        latest = client.get(
            f"/api/v1/safety/{recommendation_id}/latest",
            headers=headers,
        )
        history = client.get(
            f"/api/v1/safety/{recommendation_id}/history",
            headers=headers,
        )
        assert latest.status_code == 200
        assert latest.json()["id"] == second.json()["id"]
        assert len(history.json()["validations"]) == 2
    engine.dispose()
