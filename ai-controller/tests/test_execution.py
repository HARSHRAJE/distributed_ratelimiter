from dataclasses import replace
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from app.config import Settings
from app.execution.execution_repository import ExecutionRepository
from app.execution.execution_service import (
    ExecutionRejected,
    ExecutionService,
)
from app.execution.rollout_manager import RolloutError, RolloutManager
from app.execution.policy_client import (
    AcceptedExecution,
    EffectiveServicePolicy,
    PolicyClientError,
    ServicePolicy,
)
from app.circuit_breaker.repository import BreakerRepository
from app.safety.schemas import ValidationStatus
from app.telemetry.models import (
    Base,
    ExecutionServiceControlRecord,
    PolicyExecutionRecord,
    PolicyRecommendationRecord,
    RecommendationValidationRecord,
    ShadowEvaluationRecord,
    TelemetrySampleRecord,
)


NOW = datetime.now(timezone.utc)
SERVICE_ID = uuid4()


def settings(**overrides) -> Settings:
    values = {
        "prometheus_url": "http://prometheus:9090",
        "service_keys": ("orders-service",),
        "collection_interval_seconds": 15,
        "stale_after_seconds": 60,
        "aggregation_window_seconds": 300,
        "prometheus_timeout_seconds": 5,
        "api_key": "i" * 32,
        "db_host": "localhost",
        "db_port": 5432,
        "db_name": "test",
        "db_username": "test",
        "db_password": "test",
        "execution_enabled": True,
        "emergency_kill_switch": False,
        "execution_enabled_services": ("orders-service",),
        "policy_service_api_key": "p" * 32,
        "administrator_api_key": "a" * 32,
        "gateway_policy_cache_ttl_seconds": 0,
    }
    values.update(overrides)
    return Settings(**values)


def make_engine():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return engine


def seed(engine, *, rate: float = 105, version: int = 3):
    recommendation_id = uuid4()
    from sqlalchemy.orm import Session

    with Session(engine) as session:
        session.add(
            PolicyRecommendationRecord(
                id=recommendation_id,
                service_key="orders-service",
                scope="GLOBAL",
                current_rate=100,
                recommended_rate=rate,
                action="INCREASE",
                reason="healthy backend and capacity available",
                forecast_rps=100,
                forecast_confidence=0.95,
                safe_capacity_rps=150,
                policy_version=version,
                status="ACCEPTED",
                generated_at=NOW - timedelta(seconds=10),
                expires_at=NOW + timedelta(minutes=5),
            )
        )
        session.add(
            RecommendationValidationRecord(
                id=uuid4(),
                recommendation_id=recommendation_id,
                status=ValidationStatus.VALID.value,
                validation_result={"status": "VALID", "checks": []},
                validated_at=NOW - timedelta(seconds=5),
                validator_version="1.0",
            )
        )
        session.add(
            TelemetrySampleRecord(
                id=uuid4(),
                service_key="orders-service",
                window_start=NOW - timedelta(seconds=1),
                window_seconds=15,
                incoming_rps=98,
                allowed_rps=98,
                rejected_rps=0,
                p95_latency_ms=25,
                p99_latency_ms=50,
                error_rate=0,
                cpu_utilization=30,
                memory_utilization=50,
                redis_latency_ms=1,
                queue_depth=0,
                data_quality="valid",
                collected_at=NOW,
            )
        )
        session.add(
            ShadowEvaluationRecord(
                id=uuid4(),
                recommendation_id=recommendation_id,
                service_key="orders-service",
                current_policy_version=version,
                current_rate=100,
                proposed_rate=rate,
                actual_incoming_rps=98,
                estimated_admitted_rps=98,
                estimated_rejected_rps=0,
                evaluation_window_seconds=60,
                evaluation_result={
                    "strategies": [
                        {
                            "strategy": "FORECAST_ASSISTED",
                            "applied_global_rate_rps": rate,
                            "estimated_admitted_rps": 98,
                            "estimated_rejected_rps": 0,
                            "forecast_error_rps": 2,
                        }
                    ]
                },
                created_at=NOW - timedelta(seconds=2),
            )
        )
        session.add(
            ExecutionServiceControlRecord(
                service_key="orders-service",
                enabled=True,
                manual_override=False,
                rollout_started_at=NOW - timedelta(hours=1),
                paused_reason=None,
                updated_at=NOW - timedelta(hours=1),
            )
        )
        session.commit()
    return recommendation_id


class FakePolicyClient:
    def __init__(
        self,
        *,
        effective_version: int = 4,
        effective_rate: float = 105,
        submit_error: PolicyClientError | None = None,
        policy_unavailable: bool = False,
        effective_unavailable: bool = False,
        policy_version: int = 3,
    ) -> None:
        self.service = ServicePolicy(
            id=SERVICE_ID,
            service_key="orders-service",
            config_version=policy_version,
            global_capacity=100,
            global_refill_rate=100,
            hard_max_refill_rate=200,
            adaptive_enabled=True,
        )
        self.effective_version = effective_version
        self.effective_rate = effective_rate
        self.submit_error = submit_error
        self.policy_unavailable = policy_unavailable
        self.effective_unavailable = effective_unavailable
        self.accepted = False
        self.submit_calls = 0

    def get_service(self, service_key):
        if self.policy_unavailable:
            raise PolicyClientError("Policy Service is unavailable")
        return self.service

    def execution_status(self, service_id, execution_id):
        if self.accepted:
            return AcceptedExecution(True, 4, 105)
        return AcceptedExecution(False, None, None)

    def submit(self, service, *, execution_id, expected_version, proposed_rate):
        self.submit_calls += 1
        self.accepted = self.submit_error is not None and (
            self.effective_version == 4
        )
        if self.submit_error is not None:
            raise self.submit_error
        self.accepted = True
        self.service = replace(
            self.service,
            config_version=4,
            global_refill_rate=proposed_rate,
        )
        return self.service

    def get_effective(self, service_key):
        if self.effective_unavailable:
            raise PolicyClientError("Redis effective config is unavailable")
        return EffectiveServicePolicy(
            self.effective_version,
            self.effective_rate,
        )


def run_execution(engine, recommendation_id, monkeypatch, client, config=None):
    from sqlalchemy.orm import Session
    import app.execution.execution_service as execution_module

    monkeypatch.setattr(
        execution_module,
        "PolicyClient",
        lambda settings: client,
    )
    with Session(engine) as session:
        return ExecutionService(config or settings()).execute(
            recommendation_id,
            session=session,
            now=NOW,
        )


def test_execution_is_applied_only_after_effective_policy_is_verified(
    monkeypatch,
) -> None:
    engine = make_engine()
    recommendation_id = seed(engine)
    client = FakePolicyClient()

    result = run_execution(engine, recommendation_id, monkeypatch, client)

    assert result.status == "APPLIED"
    assert result.previous_version == 3
    assert result.resulting_version == 4
    assert all(check.passed for check in result.checks)
    assert client.submit_calls == 1


def test_policy_update_timeout_after_commit_is_reconciled_without_retry(
    monkeypatch,
) -> None:
    engine = make_engine()
    recommendation_id = seed(engine)
    client = FakePolicyClient(
        submit_error=PolicyClientError(
            "Policy Service request timed out",
            ambiguous=True,
        )
    )

    result = run_execution(engine, recommendation_id, monkeypatch, client)

    assert result.status == "APPLIED"
    assert client.submit_calls == 1


def test_ambiguous_timeout_without_confirmation_stays_pending_and_pauses(
    monkeypatch,
) -> None:
    engine = make_engine()
    recommendation_id = seed(engine)
    client = FakePolicyClient(
        effective_version=3,
        effective_rate=100,
        submit_error=PolicyClientError(
            "Policy Service request timed out",
            ambiguous=True,
        ),
    )

    result = run_execution(engine, recommendation_id, monkeypatch, client)

    assert result.status == "SUBMITTED"
    assert result.resulting_version is None
    assert client.submit_calls == 1


def test_delayed_redis_sync_never_marks_execution_applied(monkeypatch) -> None:
    engine = make_engine()
    recommendation_id = seed(engine)
    client = FakePolicyClient(effective_version=3, effective_rate=100)

    result = run_execution(engine, recommendation_id, monkeypatch, client)

    assert result.status == "SUBMITTED"
    assert result.resulting_version == 4
    assert "not synchronized" in result.failure_reason


def test_gateway_cache_expiry_is_required_before_applied(monkeypatch) -> None:
    engine = make_engine()
    recommendation_id = seed(engine)
    client = FakePolicyClient()
    config = settings(gateway_policy_cache_ttl_seconds=1)

    pending = run_execution(
        engine,
        recommendation_id,
        monkeypatch,
        client,
        config=config,
    )

    assert pending.status == "SUBMITTED"
    assert "gateway policy caches" in pending.failure_reason

    from sqlalchemy.orm import Session
    import app.execution.execution_service as execution_module

    monkeypatch.setattr(
        execution_module,
        "PolicyClient",
        lambda settings: client,
    )
    with Session(engine) as session:
        record = session.get(PolicyExecutionRecord, pending.id)
        record.effective_config_verified_at = (
            datetime.now(timezone.utc) - timedelta(seconds=2)
        )
        session.commit()
        applied = ExecutionService(config).get_status(
            pending.id,
            session=session,
        )

    assert applied.status == "APPLIED"


def test_redis_failure_never_marks_execution_applied(monkeypatch) -> None:
    engine = make_engine()
    recommendation_id = seed(engine)
    client = FakePolicyClient(effective_unavailable=True)

    result = run_execution(engine, recommendation_id, monkeypatch, client)

    assert result.status == "SUBMITTED"
    assert "unavailable" in result.failure_reason


def test_policy_service_unavailability_fails_closed(monkeypatch) -> None:
    engine = make_engine()
    recommendation_id = seed(engine)
    client = FakePolicyClient(policy_unavailable=True)

    with pytest.raises(PolicyClientError):
        run_execution(engine, recommendation_id, monkeypatch, client)

    assert client.submit_calls == 0


@pytest.mark.parametrize(
    ("changes", "expected_check"),
    [
        ({"policy_version": 2}, "POLICY_VERSION"),
        ({"rate": 106}, "MAXIMUM_CHANGE"),
        ({"execution_enabled": False}, "GLOBAL_EXECUTION_ENABLED"),
        ({"emergency_kill_switch": True}, "GLOBAL_EXECUTION_ENABLED"),
        (
            {"execution_enabled_services": ()},
            "ROLLOUT_ALLOWLIST",
        ),
    ],
)
def test_ineligible_recommendations_are_rejected_without_policy_update(
    monkeypatch,
    changes,
    expected_check,
) -> None:
    engine = make_engine()
    recommendation_id = seed(
        engine,
        rate=changes.pop("rate", 105),
        version=changes.pop("policy_version", 3),
    )
    client = FakePolicyClient()
    config = settings(**changes)
    from sqlalchemy.orm import Session
    import app.execution.execution_service as execution_module

    monkeypatch.setattr(
        execution_module,
        "PolicyClient",
        lambda settings: client,
    )
    with Session(engine) as session:
        with pytest.raises(ExecutionRejected) as error:
            ExecutionService(config).execute(
                recommendation_id,
                session=session,
                now=NOW,
            )

    assert expected_check in {check.check for check in error.value.checks}
    assert client.submit_calls == 0
    with Session(engine) as session:
        breaker = BreakerRepository(session, config).get(
            "orders-service",
            now=NOW,
        )
        assert breaker.failure_count == 0


def test_policy_version_advanced_beyond_execution_is_not_applied(monkeypatch) -> None:
    engine = make_engine()
    recommendation_id = seed(engine)
    client = FakePolicyClient(effective_version=5, effective_rate=106)

    result = run_execution(engine, recommendation_id, monkeypatch, client)

    assert result.status == "FAILED"
    assert result.status != "APPLIED"


class FakeRolloutRepository:
    def __init__(self, *, control=None, kill_switch_active=False) -> None:
        self.saved_control = control
        self.kill_switch_active = kill_switch_active

    def control(self, service_key):
        return self.saved_control

    def save_control(self, control):
        self.saved_control = control
        return control

    def global_kill_switch_active(self):
        return self.kill_switch_active

    def set_global_kill_switch(self, *, active, now):
        self.kill_switch_active = active


class FakeRolloutClient:
    def __init__(
        self,
        *,
        effective_version=2,
        policy_unavailable=False,
        kill_switch_unavailable=False,
    ) -> None:
        self.service = ServicePolicy(
            id=SERVICE_ID,
            service_key="orders-service",
            config_version=1,
            global_capacity=100,
            global_refill_rate=100,
            hard_max_refill_rate=200,
            adaptive_enabled=False,
        )
        self.effective_version = effective_version
        self.policy_unavailable = policy_unavailable
        self.kill_switch_unavailable = kill_switch_unavailable

    def get_service(self, service_key):
        if self.policy_unavailable:
            raise PolicyClientError("Policy Service is unavailable")
        return self.service

    def set_adaptive_control(
        self,
        service_key,
        *,
        expected_version,
        enabled,
    ):
        self.service = replace(
            self.service,
            config_version=expected_version + 1,
            adaptive_enabled=enabled,
        )
        return self.service

    def get_effective(self, service_key):
        return EffectiveServicePolicy(self.effective_version, 100)

    def set_global_kill_switch(self, *, active):
        if self.kill_switch_unavailable:
            raise PolicyClientError("Policy Service is unavailable")


def test_enable_keeps_execution_disabled_until_redis_sync() -> None:
    repository = FakeRolloutRepository()
    client = FakeRolloutClient(effective_version=1)

    with pytest.raises(RolloutError, match="has not synchronized"):
        RolloutManager(settings()).enable(
            "orders-service",
            repository=repository,
            client=client,
            now=NOW,
        )

    assert repository.saved_control.enabled is False
    assert repository.saved_control.paused_reason == (
        "Effective policy has not synchronized; execution remains disabled"
    )


def test_disable_is_persisted_before_policy_service_call() -> None:
    repository = FakeRolloutRepository()
    client = FakeRolloutClient(policy_unavailable=True)

    with pytest.raises(PolicyClientError, match="unavailable"):
        RolloutManager(settings(execution_enabled_services=())).disable(
            "orders-service",
            manual_override=True,
            repository=repository,
            client=client,
            now=NOW,
        )

    assert repository.saved_control.enabled is False
    assert repository.saved_control.manual_override is True


def test_failed_global_kill_switch_deactivation_stays_active() -> None:
    repository = FakeRolloutRepository(kill_switch_active=True)
    client = FakeRolloutClient(kill_switch_unavailable=True)

    with pytest.raises(PolicyClientError, match="unavailable"):
        RolloutManager(settings()).set_global_kill_switch(
            active=False,
            repository=repository,
            client=client,
            now=NOW,
        )

    assert repository.kill_switch_active is True
