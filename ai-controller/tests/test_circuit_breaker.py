from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.circuit_breaker.repository import BreakerRejected, BreakerRepository
from app.circuit_breaker.schemas import BreakerState
from app.circuit_breaker.health_evaluator import HealthEvaluator
from app.circuit_breaker.execution_guard import ExecutionGuard
from app.config import Settings
from app.telemetry.models import (
    AdaptiveExecutionReservationRecord,
    Base,
    ExecutionGlobalControlRecord,
    PolicyExecutionRecord,
    PolicyRecommendationRecord,
    TelemetrySampleRecord,
)


NOW = datetime.now(timezone.utc)


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
        "breaker_recovery_timeout_seconds": 10,
    }
    values.update(overrides)
    return Settings(**values)


def engine():
    database = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(database)
    return database


def seed_recommendation(session: Session, *, action: str = "DECREASE"):
    recommendation = PolicyRecommendationRecord(
        id=uuid4(),
        service_key="orders-service",
        scope="GLOBAL",
        current_rate=100,
        recommended_rate=99,
        action=action,
        reason="test recovery",
        forecast_rps=100,
        forecast_confidence=0.95,
        safe_capacity_rps=150,
        policy_version=1,
        status="ACCEPTED",
        generated_at=NOW,
        expires_at=NOW + timedelta(minutes=5),
    )
    session.add(recommendation)
    session.commit()
    return recommendation


def open_after_failures(session: Session, config: Settings) -> None:
    repository = BreakerRepository(session, config)
    for number in range(config.breaker_failure_threshold):
        repository.fail_service(
            "orders-service",
            f"execution failure {number}",
            now=NOW + timedelta(seconds=number),
        )


def test_three_consecutive_failures_open_and_persist_breaker():
    database = engine()
    config = settings()
    with Session(database) as session:
        open_after_failures(session, config)
        breaker = BreakerRepository(session, config).get(
            "orders-service",
            now=NOW,
        )
        assert breaker.state == BreakerState.OPEN.value
        assert breaker.failure_count == 3
        assert len(BreakerRepository(session, config).events(
            "orders-service",
            limit=10,
        )) == 1

    with Session(database) as session:
        restored = BreakerRepository(session, config).get(
            "orders-service",
            now=NOW,
        )
        assert restored.state == BreakerState.OPEN.value


def test_open_breaker_rejects_reservation_until_recovery_timeout():
    database = engine()
    config = settings()
    with Session(database) as session:
        recommendation = seed_recommendation(session)
        open_after_failures(session, config)
        with pytest.raises(BreakerRejected, match="OPEN"):
            BreakerRepository(session, config).reserve(
                service_key="orders-service",
                recommendation_id=recommendation.id,
                action="DECREASE",
                current_rate=100,
                proposed_rate=99,
                now=NOW + timedelta(seconds=5),
            )


def test_half_open_allows_one_small_decrease_then_closes_on_success():
    database = engine()
    config = settings()
    with Session(database) as session:
        recommendation = seed_recommendation(session)
        open_after_failures(session, config)
        repository = BreakerRepository(session, config)
        reservation = repository.reserve(
            service_key="orders-service",
            recommendation_id=recommendation.id,
            action="DECREASE",
            current_rate=100,
            proposed_rate=99,
            now=NOW + timedelta(seconds=20),
        )
        breaker = repository.get("orders-service", now=NOW)
        assert breaker.state == BreakerState.HALF_OPEN.value
        assert reservation.recovery_check

        with pytest.raises(BreakerRejected, match="DECREASE"):
            repository.reserve(
                service_key="orders-service",
                recommendation_id=uuid4(),
                action="INCREASE",
                current_rate=100,
                proposed_rate=101,
                now=NOW + timedelta(seconds=21),
            )

        repository.release(
            reservation.id,
            now=NOW + timedelta(seconds=22),
            success=True,
        )
        assert repository.get("orders-service", now=NOW).state == (
            BreakerState.CLOSED.value
        )


def test_failed_half_open_recovery_returns_to_open():
    database = engine()
    config = settings()
    with Session(database) as session:
        recommendation = seed_recommendation(session)
        open_after_failures(session, config)
        repository = BreakerRepository(session, config)
        reservation = repository.reserve(
            service_key="orders-service",
            recommendation_id=recommendation.id,
            action="DECREASE",
            current_rate=100,
            proposed_rate=99,
            now=NOW + timedelta(seconds=20),
        )
        repository.release(
            reservation.id,
            now=NOW + timedelta(seconds=21),
            success=False,
            failure_reason="recovery check failed",
        )
        assert repository.get("orders-service", now=NOW).state == (
            BreakerState.OPEN.value
        )


def test_non_execution_rejection_releases_reservation_without_counting_failure():
    database = engine()
    config = settings()
    with Session(database) as session:
        recommendation = seed_recommendation(session)
        repository = BreakerRepository(session, config)
        reservation = repository.reserve(
            service_key="orders-service",
            recommendation_id=recommendation.id,
            action="DECREASE",
            current_rate=100,
            proposed_rate=99,
            now=NOW,
        )

        repository.release(
            reservation.id,
            now=NOW + timedelta(seconds=1),
            success=None,
            failure_reason="Recommendation was ineligible",
        )

        breaker = repository.get("orders-service", now=NOW)
        assert breaker.state == BreakerState.CLOSED.value
        assert breaker.failure_count == 0


def test_emergency_kill_switch_during_recovery_cannot_close_breaker():
    database = engine()
    config = settings()
    with Session(database) as session:
        recommendation = seed_recommendation(session)
        open_after_failures(session, config)
        repository = BreakerRepository(session, config)
        reservation = repository.reserve(
            service_key="orders-service",
            recommendation_id=recommendation.id,
            action="DECREASE",
            current_rate=100,
            proposed_rate=99,
            now=NOW + timedelta(seconds=20),
        )
        session.add(
            ExecutionGlobalControlRecord(
                id="global",
                kill_switch_active=True,
                updated_at=NOW + timedelta(seconds=21),
            )
        )
        session.commit()
        repository.release(
            reservation.id,
            now=NOW + timedelta(seconds=21),
            success=True,
        )
        state = repository.get("orders-service", now=NOW)
        assert state.state == BreakerState.OPEN.value
        assert "emergency" in state.last_failure_reason.lower()


def test_component_failures_are_independent_from_service_breaker_state():
    database = engine()
    config = settings()
    with Session(database) as session:
        repository = BreakerRepository(session, config)
        for number in range(config.breaker_policy_failure_threshold):
            repository.report_component(
                "orders-service",
                "POLICY_SERVICE",
                healthy=False,
                reason=f"policy request failure {number}",
                failure_threshold=config.breaker_policy_failure_threshold,
                now=NOW + timedelta(seconds=number),
            )
        state = repository.get("orders-service", now=NOW)
        component = repository.components("orders-service")[0]
        assert component.state == BreakerState.OPEN.value
        assert state.state == BreakerState.CLOSED.value


def test_manual_disable_overrides_timeout_and_recovery_transitions():
    database = engine()
    config = settings()
    with Session(database) as session:
        recommendation = seed_recommendation(session)
        repository = BreakerRepository(session, config)
        repository.manual_open("orders-service", "operator emergency", now=NOW)
        with pytest.raises(BreakerRejected, match="manually disabled"):
            repository.reserve(
                service_key="orders-service",
                recommendation_id=recommendation.id,
                action="DECREASE",
                current_rate=100,
                proposed_rate=99,
                now=NOW + timedelta(hours=1),
            )

        with pytest.raises(BreakerRejected, match="explicit administrator"):
            repository.request_recovery(
                "orders-service",
                clear_manual_disable=False,
                now=NOW + timedelta(hours=1),
            )

        repository.request_recovery(
            "orders-service",
            clear_manual_disable=True,
            now=NOW + timedelta(hours=1),
        )
        assert repository.get("orders-service", now=NOW).state == (
            BreakerState.HALF_OPEN.value
        )


def test_a_service_has_a_single_durable_active_reservation():
    database = engine()
    config = settings()
    with Session(database) as session:
        first = seed_recommendation(session)
        second = seed_recommendation(session)
        repository = BreakerRepository(session, config)
        repository.reserve(
            service_key="orders-service",
            recommendation_id=first.id,
            action="DECREASE",
            current_rate=100,
            proposed_rate=99,
            now=NOW,
        )
        with pytest.raises(BreakerRejected, match="Another adaptive"):
            repository.reserve(
                service_key="orders-service",
                recommendation_id=second.id,
                action="DECREASE",
                current_rate=100,
                proposed_rate=99,
                now=NOW,
            )
        active = session.scalars(
            select(AdaptiveExecutionReservationRecord).where(
                AdaptiveExecutionReservationRecord.active.is_(True)
            )
        ).all()
        assert len(active) == 1


def test_stale_telemetry_opens_breaker_and_blocks_execution():
    database = engine()
    config = settings()
    with Session(database) as session:
        recommendation = seed_recommendation(session)
        stale_sample = TelemetrySampleRecord(
            id=uuid4(),
            service_key="orders-service",
            window_start=NOW - timedelta(seconds=120),
            window_seconds=15,
            incoming_rps=100,
            allowed_rps=100,
            rejected_rps=0,
            p95_latency_ms=25,
            p99_latency_ms=50,
            error_rate=0,
            cpu_utilization=30,
            memory_utilization=50,
            redis_latency_ms=1,
            queue_depth=0,
            data_quality="valid",
            collected_at=NOW - timedelta(seconds=120),
        )
        session.add(stale_sample)
        session.commit()

        with pytest.raises(BreakerRejected, match="OPEN"):
            ExecutionGuard(config).reserve(
                service_key="orders-service",
                recommendation_id=recommendation.id,
                action="DECREASE",
                current_rate=100,
                proposed_rate=99,
                session=session,
                now=NOW,
            )
        state = BreakerRepository(session, config).get(
            "orders-service",
            now=NOW,
        )
        assert state.state == BreakerState.OPEN.value
        assert state.failure_count == config.breaker_failure_threshold

        HealthEvaluator(config).evaluate(
            "orders-service",
            session=session,
            now=NOW + timedelta(seconds=1),
        )
        assert state.failure_count == config.breaker_failure_threshold


def test_redis_sync_timeout_opens_breaker_and_component_health():
    database = engine()
    config = settings()
    with Session(database) as session:
        recommendation = seed_recommendation(session)
        session.add(
            PolicyExecutionRecord(
                id=uuid4(),
                recommendation_id=recommendation.id,
                service_key="orders-service",
                policy_id=None,
                previous_version=1,
                resulting_version=2,
                effective_config_verified_at=None,
                previous_rate=100,
                proposed_rate=99,
                status="SUBMITTED",
                failure_reason=None,
                started_at=NOW - timedelta(seconds=120),
                completed_at=None,
            )
        )
        session.commit()

        HealthEvaluator(config).evaluate(
            "orders-service",
            session=session,
            now=NOW,
        )
        state = BreakerRepository(session, config).get(
            "orders-service",
            now=NOW,
        )
        components = {
            item.component: item
            for item in BreakerRepository(session, config).components(
                "orders-service"
            )
        }
        assert state.state == BreakerState.OPEN.value
        assert components["REDIS_SYNC"].state == BreakerState.OPEN.value
