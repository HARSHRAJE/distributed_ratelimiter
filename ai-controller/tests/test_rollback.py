from dataclasses import replace
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.config import Settings
from app.execution.policy_client import (
    AcceptedRollback,
    EffectiveServicePolicy,
    PolicyClientError,
    ServicePolicy,
)
from app.rollback.rollback_service import RollbackError, RollbackService
from app.telemetry.models import (
    Base,
    ExecutionServiceControlRecord,
    PolicyExecutionRecord,
    PolicyRecommendationRecord,
    PolicyRollbackEventRecord,
    TelemetrySampleRecord,
)


NOW = datetime(2026, 11, 5, 12, 0, tzinfo=timezone.utc)
SERVICE_ID = uuid4()
EXECUTION_ID = uuid4()
RECOMMENDATION_ID = uuid4()


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
        "policy_service_api_key": "p" * 32,
        "gateway_policy_cache_ttl_seconds": 0,
        "rollback_observation_period_seconds": 1,
        "rollback_cooldown_seconds": 10,
        "rollback_minimum_healthy_windows": 2,
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


def seed(
    engine,
    *,
    p95_values=(100, 100, 100, 100, 100),
    error_rates=(0, 0, 0, 0, 0),
    cpu_values=(30, 30, 30, 30, 30),
    queue_values=(0, 0, 0, 0, 0),
    allowed_values=(100, 100, 100, 100, 100),
    window_spacing_seconds=2,
    execution_status="APPLIED",
    completed_at=NOW - timedelta(seconds=10),
) -> None:
    with Session(engine) as session:
        session.add(
            PolicyRecommendationRecord(
                id=RECOMMENDATION_ID,
                service_key="orders-service",
                scope="GLOBAL",
                current_rate=100,
                recommended_rate=120,
                action="INCREASE",
                reason="healthy backend and capacity available",
                forecast_rps=100,
                forecast_confidence=0.95,
                safe_capacity_rps=150,
                policy_version=3,
                status="ACCEPTED",
                generated_at=NOW - timedelta(minutes=5),
                expires_at=NOW + timedelta(minutes=5),
            )
        )
        session.add(
            PolicyExecutionRecord(
                id=EXECUTION_ID,
                recommendation_id=RECOMMENDATION_ID,
                service_key="orders-service",
                policy_id=None,
                previous_version=3,
                resulting_version=4,
                effective_config_verified_at=completed_at,
                previous_rate=100,
                proposed_rate=120,
                status=execution_status,
                failure_reason=None,
                started_at=NOW - timedelta(seconds=30),
                completed_at=completed_at,
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
        session.add(
            TelemetrySampleRecord(
                id=uuid4(),
                service_key="orders-service",
                window_start=NOW - timedelta(seconds=40),
                window_seconds=15,
                incoming_rps=100,
                allowed_rps=100,
                rejected_rps=0,
                p95_latency_ms=100,
                p99_latency_ms=150,
                error_rate=0,
                cpu_utilization=30,
                memory_utilization=50,
                redis_latency_ms=1,
                queue_depth=0,
                data_quality="valid",
                collected_at=NOW - timedelta(seconds=40),
            )
        )
        for index in range(len(p95_values)):
            timestamp = NOW - timedelta(seconds=9) + timedelta(
                seconds=index * window_spacing_seconds
            )
            session.add(
                TelemetrySampleRecord(
                    id=uuid4(),
                    service_key="orders-service",
                    window_start=timestamp,
                    window_seconds=15,
                    incoming_rps=100,
                    allowed_rps=allowed_values[index],
                    rejected_rps=0,
                    p95_latency_ms=p95_values[index],
                    p99_latency_ms=150,
                    error_rate=error_rates[index],
                    cpu_utilization=cpu_values[index],
                    memory_utilization=50,
                    redis_latency_ms=1,
                    queue_depth=queue_values[index],
                    data_quality="valid",
                    collected_at=timestamp,
                )
            )
        session.commit()


class FakePolicyClient:
    def __init__(
        self,
        *,
        current_version=4,
        effective_version=5,
        effective_rate=100,
        rollback_error=None,
        effective_unavailable=False,
    ) -> None:
        self.service = ServicePolicy(
            id=SERVICE_ID,
            service_key="orders-service",
            config_version=current_version,
            global_capacity=100,
            global_refill_rate=120,
            hard_max_refill_rate=200,
            adaptive_enabled=True,
        )
        self.effective_version = effective_version
        self.effective_rate = effective_rate
        self.rollback_error = rollback_error
        self.effective_unavailable = effective_unavailable
        self.accepted = False
        self.rollback_calls = 0

    def get_service(self, service_key):
        return self.service

    def rollback_status(self, service_id, rollback_id):
        if self.accepted:
            return AcceptedRollback(True, 5, 100)
        return AcceptedRollback(False, None, None)

    def rollback_service(
        self,
        service,
        *,
        rollback_id,
        expected_active_version,
        restored_from_version,
    ):
        self.rollback_calls += 1
        if self.rollback_error:
            raise self.rollback_error
        self.accepted = True
        self.service = replace(
            self.service,
            config_version=expected_active_version + 1,
            global_refill_rate=100,
            adaptive_enabled=False,
        )
        return AcceptedRollback(True, expected_active_version + 1, 100)

    def get_effective(self, service_key):
        if self.effective_unavailable:
            raise PolicyClientError(
                "Redis effective config is unavailable",
                status_code=503,
            )
        return EffectiveServicePolicy(
            self.effective_version,
            self.effective_rate,
        )


def evaluate(engine, config=None, *, now=NOW + timedelta(seconds=20)):
    with Session(engine) as session:
        return RollbackService(config or settings()).evaluate(
            "orders-service",
            session=session,
            now=now,
        )


def test_healthy_service_does_not_trigger_rollback() -> None:
    engine = make_engine()
    seed(engine)

    result = evaluate(engine)

    assert result.eligible is True
    assert result.triggered is False


def test_sustained_high_latency_triggers_rollback() -> None:
    engine = make_engine()
    seed(engine, p95_values=(100, 100, 600, 700, 800))

    result = evaluate(engine)

    assert result.triggered is True
    assert "P95_LATENCY" in {trigger.metric for trigger in result.triggers}


def test_single_latency_spike_does_not_trigger_rollback() -> None:
    engine = make_engine()
    seed(engine, p95_values=(100, 100, 1000, 100, 100))

    result = evaluate(engine)

    assert result.triggered is False


def test_missing_telemetry_windows_break_consecutive_thresholds() -> None:
    engine = make_engine()
    seed(
        engine,
        p95_values=(100, 100, 600, 700, 800),
        window_spacing_seconds=30,
    )

    result = evaluate(engine, now=NOW + timedelta(seconds=120))

    assert result.triggered is False


def test_sustained_5xx_rate_triggers_rollback() -> None:
    engine = make_engine()
    seed(engine, error_rates=(0, 0, 6, 6, 6))

    result = evaluate(engine)

    assert result.triggered is True
    assert "5XX_ERROR_RATE" in {trigger.metric for trigger in result.triggers}


def test_critical_5xx_rate_triggers_before_observation_period() -> None:
    engine = make_engine()
    completed = NOW - timedelta(seconds=2)
    seed(
        engine,
        error_rates=(0, 0, 0, 0, 21),
        completed_at=completed,
    )

    result = evaluate(
        engine,
        settings(rollback_observation_period_seconds=1000),
        now=NOW,
    )

    assert result.triggered is True
    assert result.triggers[0].critical is True


def test_redis_sync_timeout_triggers_immediate_rollback_evaluation() -> None:
    engine = make_engine()
    seed(engine, execution_status="SUBMITTED", completed_at=None)

    result = evaluate(
        engine,
        settings(rollback_redis_sync_timeout_seconds=60),
        now=NOW + timedelta(seconds=100),
    )

    assert result.triggered is True
    assert result.triggers[0].metric == "REDIS_SYNC"
    assert result.triggers[0].critical is True


def test_sustained_cpu_and_growing_queue_trigger_rollback() -> None:
    engine = make_engine()
    seed(
        engine,
        cpu_values=(30, 91, 92, 93, 94),
        queue_values=(0, 120, 130, 140, 150),
    )

    result = evaluate(engine)

    assert {"CPU_UTILIZATION", "QUEUE_GROWTH"} <= {
        trigger.metric for trigger in result.triggers
    }


def test_sustained_throughput_degradation_triggers_rollback() -> None:
    engine = make_engine()
    seed(engine, allowed_values=(100, 60, 60, 60, 60))

    result = evaluate(engine)

    assert result.triggered is True
    assert "THROUGHPUT_DEGRADATION" in {
        trigger.metric for trigger in result.triggers
    }


def test_rollback_restores_previous_version_as_new_policy_and_pauses_control(
    monkeypatch,
) -> None:
    engine = make_engine()
    seed(p95_values=(100, 100, 600, 700, 800), engine=engine)
    client = FakePolicyClient()
    import app.rollback.rollback_service as module

    monkeypatch.setattr(module, "PolicyClient", lambda config: client)

    with Session(engine) as session:
        event = RollbackService(settings()).execute(
            EXECUTION_ID,
            session=session,
            now=NOW + timedelta(seconds=20),
        )
        control = session.get(
            ExecutionServiceControlRecord,
            "orders-service",
        )
        execution = session.get(PolicyExecutionRecord, EXECUTION_ID)

    assert event.status == "COMPLETED"
    assert event.failed_version == 4
    assert event.restored_from_version == 3
    assert event.rollback_version == 5
    assert client.rollback_calls == 1
    assert control.enabled is False
    assert execution.status == "ROLLED_BACK"
    assert execution.resulting_version == 5


def test_manual_policy_change_prevents_stale_rollback(monkeypatch) -> None:
    engine = make_engine()
    seed(p95_values=(100, 100, 600, 700, 800), engine=engine)
    client = FakePolicyClient(current_version=5)
    import app.rollback.rollback_service as module

    monkeypatch.setattr(module, "PolicyClient", lambda config: client)

    with Session(engine) as session:
        event = RollbackService(settings()).execute(
            EXECUTION_ID,
            session=session,
            now=NOW + timedelta(seconds=20),
        )

    assert event.status == "FAILED"
    assert "concurrent administrator update" in event.reason
    assert client.rollback_calls == 0


def test_redis_sync_delay_keeps_rollback_pending(monkeypatch) -> None:
    engine = make_engine()
    seed(p95_values=(100, 100, 600, 700, 800), engine=engine)
    client = FakePolicyClient(effective_version=4, effective_rate=120)
    import app.rollback.rollback_service as module

    monkeypatch.setattr(module, "PolicyClient", lambda config: client)

    with Session(engine) as session:
        event = RollbackService(settings()).execute(
            EXECUTION_ID,
            session=session,
            now=NOW + timedelta(seconds=20),
        )

    assert event.status == "POLICY_RESTORED"
    assert event.rollback_version == 5


def test_redis_sync_timeout_marks_rollback_failed_and_alerts(monkeypatch) -> None:
    engine = make_engine()
    seed(p95_values=(100, 100, 600, 700, 800), engine=engine)
    client = FakePolicyClient(effective_unavailable=True)
    import app.rollback.rollback_service as module

    monkeypatch.setattr(module, "PolicyClient", lambda config: client)
    service = RollbackService(
        settings(rollback_redis_sync_timeout_seconds=60)
    )
    with Session(engine) as session:
        pending = service.execute(
            EXECUTION_ID,
            session=session,
            now=NOW + timedelta(seconds=20),
        )
        failed = service.execute(
            EXECUTION_ID,
            session=session,
            now=NOW + timedelta(seconds=90),
        )

    assert pending.status == "POLICY_RESTORED"
    assert failed.status == "FAILED"
    assert "synchronization timeout" in failed.reason
    assert module.ROLLBACK_FAILURES.labels(
        service_key="orders-service",
        reason="P95_LATENCY",
    )._value.get() >= 1


def test_duplicate_rollback_request_does_not_create_another_policy_version(
    monkeypatch,
) -> None:
    engine = make_engine()
    seed(p95_values=(100, 100, 600, 700, 800), engine=engine)
    client = FakePolicyClient()
    import app.rollback.rollback_service as module

    monkeypatch.setattr(module, "PolicyClient", lambda config: client)
    service = RollbackService(settings())

    with Session(engine) as session:
        first = service.execute(
            EXECUTION_ID,
            session=session,
            now=NOW + timedelta(seconds=20),
        )
        second = service.execute(
            EXECUTION_ID,
            session=session,
            now=NOW + timedelta(seconds=21),
        )

    assert first.id == second.id
    assert second.rollback_version == 5
    assert client.rollback_calls == 1


def test_rollback_failure_is_persisted_and_alerted(monkeypatch) -> None:
    engine = make_engine()
    seed(p95_values=(100, 100, 600, 700, 800), engine=engine)
    client = FakePolicyClient(
        rollback_error=PolicyClientError(
            "Policy Service rejected rollback",
            status_code=409,
        )
    )
    import app.rollback.rollback_service as module

    monkeypatch.setattr(module, "PolicyClient", lambda config: client)

    with Session(engine) as session:
        event = RollbackService(settings()).execute(
            EXECUTION_ID,
            session=session,
            now=NOW + timedelta(seconds=20),
        )

    assert event.status == "FAILED"
    assert event.completed_at is not None
    assert module.ROLLBACK_FAILURES.labels(
        service_key="orders-service",
        reason="P95_LATENCY",
    )._value.get() >= 1


def test_rollback_attempt_limit_fails_closed_and_requires_operator_review() -> None:
    engine = make_engine()
    seed(engine, p95_values=(100, 100, 600, 700, 800))
    prior_execution_id = uuid4()
    with Session(engine) as session:
        session.add(
            PolicyExecutionRecord(
                id=prior_execution_id,
                recommendation_id=RECOMMENDATION_ID,
                service_key="orders-service",
                policy_id=None,
                previous_version=2,
                resulting_version=3,
                effective_config_verified_at=NOW - timedelta(hours=1),
                previous_rate=90,
                proposed_rate=100,
                status="FAILED",
                failure_reason="previous rollback failed",
                started_at=NOW - timedelta(hours=1),
                completed_at=NOW - timedelta(minutes=30),
            )
        )
        session.add(
            PolicyRollbackEventRecord(
                id=uuid4(),
                execution_id=prior_execution_id,
                service_key="orders-service",
                failed_version=3,
                restored_from_version=2,
                rollback_version=None,
                trigger_metric="P95_LATENCY",
                trigger_value=600,
                threshold_value=500,
                reason="previous rollback failed",
                status="FAILED",
                created_at=NOW - timedelta(minutes=30),
                completed_at=NOW - timedelta(minutes=29),
                effective_config_verified_at=None,
            )
        )
        session.commit()

        event = RollbackService(
            settings(rollback_max_attempts_per_hour=1)
        ).execute(
            EXECUTION_ID,
            session=session,
            now=NOW + timedelta(seconds=20),
        )
        with pytest.raises(RollbackError, match="explicit administrator approval"):
            RollbackService(
                settings(rollback_max_attempts_per_hour=1)
            ).ensure_resume_allowed(
                "orders-service",
                session=session,
                now=NOW + timedelta(seconds=40),
            )

    assert event.status == "FAILED"
    assert "attempts per hour" in event.reason


def test_minimum_healthy_period_and_cooldown_gate_reenable() -> None:
    engine = make_engine()
    seed(engine)
    completed_at = NOW
    with Session(engine) as session:
        session.add(
            PolicyRollbackEventRecord(
                id=uuid4(),
                execution_id=EXECUTION_ID,
                service_key="orders-service",
                failed_version=4,
                restored_from_version=3,
                rollback_version=5,
                trigger_metric="P95_LATENCY",
                trigger_value=600,
                threshold_value=500,
                reason="sustained latency",
                status="COMPLETED",
                created_at=NOW - timedelta(minutes=1),
                completed_at=completed_at,
                effective_config_verified_at=completed_at,
            )
        )
        session.commit()

        service = RollbackService(
            settings(rollback_cooldown_seconds=30)
        )
        with pytest.raises(RollbackError, match="cooldown"):
            service.ensure_resume_allowed(
                "orders-service",
                session=session,
                now=NOW + timedelta(seconds=20),
            )
        with pytest.raises(RollbackError, match="healthy observation"):
            service.ensure_resume_allowed(
                "orders-service",
                session=session,
                now=NOW + timedelta(seconds=40),
            )


def test_healthy_observation_after_cooldown_allows_admin_resume() -> None:
    engine = make_engine()
    seed(engine)
    completed_at = NOW
    with Session(engine) as session:
        session.add(
            PolicyRollbackEventRecord(
                id=uuid4(),
                execution_id=EXECUTION_ID,
                service_key="orders-service",
                failed_version=4,
                restored_from_version=3,
                rollback_version=5,
                trigger_metric="P95_LATENCY",
                trigger_value=600,
                threshold_value=500,
                reason="sustained latency",
                status="COMPLETED",
                created_at=NOW - timedelta(minutes=1),
                completed_at=completed_at,
                effective_config_verified_at=completed_at,
            )
        )
        for offset in (30, 35):
            timestamp = NOW + timedelta(seconds=offset)
            session.add(
                TelemetrySampleRecord(
                    id=uuid4(),
                    service_key="orders-service",
                    window_start=timestamp,
                    window_seconds=15,
                    incoming_rps=100,
                    allowed_rps=100,
                    rejected_rps=0,
                    p95_latency_ms=100,
                    p99_latency_ms=150,
                    error_rate=0,
                    cpu_utilization=30,
                    memory_utilization=50,
                    redis_latency_ms=1,
                    queue_depth=0,
                    data_quality="valid",
                    collected_at=timestamp,
                )
            )
        session.commit()

        RollbackService(
            settings(
                rollback_cooldown_seconds=10,
                rollback_minimum_healthy_windows=2,
            )
        ).ensure_resume_allowed(
            "orders-service",
            session=session,
            now=NOW + timedelta(seconds=40),
        )
