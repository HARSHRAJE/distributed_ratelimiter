from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.circuit_breaker.breaker_config import BreakerConfig
from app.circuit_breaker.breaker_state import BreakerState
from app.circuit_breaker.state_machine import recovery_deadline, recovery_ready
from app.telemetry.models import (
    AdaptiveControlBreakerRecord,
    AdaptiveExecutionReservationRecord,
    CircuitBreakerEventRecord,
    ComponentHealthBreakerRecord,
    ExecutionGlobalControlRecord,
    ExecutionServiceControlRecord,
)


class BreakerRejected(RuntimeError):
    pass


class BreakerRepository:
    def __init__(self, session: Session, settings) -> None:
        self.session = session
        self.config = BreakerConfig.from_settings(settings)

    def ensure(self, service_key: str, *, now: datetime) -> AdaptiveControlBreakerRecord:
        record = self.session.scalar(
            select(AdaptiveControlBreakerRecord).where(
                AdaptiveControlBreakerRecord.service_key == service_key
            )
        )
        if record is not None:
            return record
        record = AdaptiveControlBreakerRecord(
            id=uuid4(),
            service_key=service_key,
            state=BreakerState.CLOSED.value,
            failure_count=0,
            success_count=0,
            half_open_attempts=0,
            opened_at=None,
            next_attempt_at=None,
            last_failure_reason=None,
            manual_disabled=False,
            updated_at=now,
        )
        self.session.add(record)
        try:
            self.session.commit()
        except IntegrityError:
            self.session.rollback()
            record = self.session.scalar(
                select(AdaptiveControlBreakerRecord).where(
                    AdaptiveControlBreakerRecord.service_key == service_key
                )
            )
            if record is None:
                raise
        return record

    def get(self, service_key: str, *, now: datetime) -> AdaptiveControlBreakerRecord:
        return self.ensure(service_key, now=now)

    def get_for_service_reservation(
        self,
        reservation_id: UUID,
        *,
        now: datetime,
    ) -> AdaptiveControlBreakerRecord | None:
        reservation = self.session.get(
            AdaptiveExecutionReservationRecord,
            reservation_id,
        )
        if reservation is None:
            return None
        return self.get(reservation.service_key, now=now)

    def lock(self, service_key: str, *, now: datetime) -> AdaptiveControlBreakerRecord:
        self.ensure(service_key, now=now)
        record = self.session.scalar(
            select(AdaptiveControlBreakerRecord)
            .where(AdaptiveControlBreakerRecord.service_key == service_key)
            .with_for_update()
        )
        if record is None:
            raise RuntimeError("Breaker state disappeared while acquiring lock")
        return record

    def events(self, service_key: str, *, limit: int) -> list[CircuitBreakerEventRecord]:
        return list(
            self.session.scalars(
                select(CircuitBreakerEventRecord)
                .where(CircuitBreakerEventRecord.service_key == service_key)
                .order_by(CircuitBreakerEventRecord.created_at.desc())
                .limit(limit)
            ).all()
        )

    def components(self, service_key: str) -> list[ComponentHealthBreakerRecord]:
        return list(
            self.session.scalars(
                select(ComponentHealthBreakerRecord)
                .where(ComponentHealthBreakerRecord.service_key == service_key)
                .order_by(ComponentHealthBreakerRecord.component)
            ).all()
        )

    def reserve(
        self,
        *,
        service_key: str,
        recommendation_id: UUID,
        action: str,
        current_rate: float,
        proposed_rate: float,
        now: datetime,
    ) -> AdaptiveExecutionReservationRecord:
        state = self.lock(service_key, now=now)
        if state.manual_disabled:
            self.session.rollback()
            raise BreakerRejected("Adaptive control is manually disabled")
        emergency = self.session.get(ExecutionGlobalControlRecord, "global")
        if emergency is not None and emergency.kill_switch_active:
            self.session.rollback()
            raise BreakerRejected("Global emergency kill switch is active")
        control = self.session.get(ExecutionServiceControlRecord, service_key)
        if control is not None and control.manual_override:
            self.session.rollback()
            raise BreakerRejected("Adaptive control is under manual override")

        if state.state == BreakerState.OPEN.value:
            if not recovery_ready(
                state=state.state,
                next_attempt_at=state.next_attempt_at,
                now=now,
            ):
                self.session.rollback()
                raise BreakerRejected("Circuit breaker is OPEN")
            self._transition(
                state,
                BreakerState.HALF_OPEN.value,
                "Recovery timeout elapsed; awaiting a limited recovery check",
                "automatic",
                now,
            )
            state.success_count = 0
            state.half_open_attempts = 0

        if state.state == BreakerState.HALF_OPEN.value:
            if action != "DECREASE":
                self.session.rollback()
                raise BreakerRejected(
                    "HALF_OPEN permits only a limited DECREASE recovery check"
                )
            if current_rate <= 0 or (
                abs(proposed_rate - current_rate) / current_rate * 100
                > self.config.recovery_max_change_percent
            ):
                self.session.rollback()
                raise BreakerRejected(
                    "Recovery check exceeds the configured change limit"
                )

        unhealthy = [
            item.component
            for item in self.components(service_key)
            if item.state != BreakerState.CLOSED.value
        ]
        if unhealthy:
            self.session.rollback()
            raise BreakerRejected(
                "Unhealthy controller components block execution: "
                + ", ".join(unhealthy)
            )

        active = list(
            self.session.scalars(
                select(AdaptiveExecutionReservationRecord)
                .where(
                    AdaptiveExecutionReservationRecord.service_key == service_key,
                    AdaptiveExecutionReservationRecord.active.is_(True),
                )
                .with_for_update()
            ).all()
        )
        existing = next(
            (
                reservation
                for reservation in active
                if reservation.recommendation_id == recommendation_id
            ),
            None,
        )
        if existing is not None:
            if state.state == BreakerState.HALF_OPEN.value and not existing.recovery_check:
                self.session.rollback()
                raise BreakerRejected("Existing reservation is not a recovery check")
            self.session.commit()
            return existing
        if (
            state.state == BreakerState.HALF_OPEN.value
            and state.half_open_attempts
            >= self.config.half_open_max_calls
        ):
            self.session.rollback()
            raise BreakerRejected(
                "HALF_OPEN recovery-check limit has been reached"
            )
        if active:
            self.session.rollback()
            raise BreakerRejected("Another adaptive execution is reserved")
        reservation = self.session.scalar(
            select(AdaptiveExecutionReservationRecord)
            .where(
                AdaptiveExecutionReservationRecord.service_key == service_key,
                AdaptiveExecutionReservationRecord.recommendation_id
                == recommendation_id,
            )
            .with_for_update()
        )
        is_recovery = state.state == BreakerState.HALF_OPEN.value
        if reservation is None:
            reservation = AdaptiveExecutionReservationRecord(
                id=uuid4(),
                service_key=service_key,
                recommendation_id=recommendation_id,
                active=True,
                recovery_check=is_recovery,
                created_at=now,
                released_at=None,
            )
            self.session.add(reservation)
        else:
            reservation.active = True
            reservation.recovery_check = is_recovery
            reservation.created_at = now
            reservation.released_at = None
        if is_recovery:
            state.half_open_attempts += 1
        self.session.commit()
        self.session.refresh(reservation)
        return reservation

    def release(
        self,
        reservation_id: UUID,
        *,
        now: datetime,
        success: bool | None,
        failure_reason: str | None = None,
    ) -> None:
        reservation = self.session.get(
            AdaptiveExecutionReservationRecord,
            reservation_id,
        )
        if reservation is None or not reservation.active:
            return
        state = self.lock(reservation.service_key, now=now)
        reservation.active = False
        reservation.released_at = now
        if success is True:
            state.failure_count = 0
            state.last_failure_reason = None
            state.success_count += 1
            global_control = self.session.get(
                ExecutionGlobalControlRecord,
                "global",
            )
            service_control = self.session.get(
                ExecutionServiceControlRecord,
                reservation.service_key,
            )
            manual_override_active = (
                state.manual_disabled
                or (
                    global_control is not None
                    and global_control.kill_switch_active
                )
                or (
                    service_control is not None
                    and service_control.manual_override
                )
            )
            if (
                reservation.recovery_check
                and state.state == BreakerState.HALF_OPEN.value
                and manual_override_active
            ):
                reason = "Manual emergency disable prevents automatic recovery"
                state.failure_count = max(
                    state.failure_count,
                    self.config.failure_threshold,
                )
                state.last_failure_reason = reason
                state.opened_at = now
                state.next_attempt_at = recovery_deadline(
                    now,
                    self.config.recovery_timeout_seconds,
                )
                self._transition(
                    state,
                    BreakerState.OPEN.value,
                    reason,
                    "automatic",
                    now,
                )
            elif (
                reservation.recovery_check
                and state.state == BreakerState.HALF_OPEN.value
                and state.success_count >= self.config.success_threshold
            ):
                state.success_count = 0
                state.half_open_attempts = 0
                state.opened_at = None
                state.next_attempt_at = None
                self._transition(
                    state,
                    BreakerState.CLOSED.value,
                    "Recovery check succeeded",
                    "automatic",
                    now,
                )
        elif success is False or reservation.recovery_check:
            self._fail_service(
                state,
                failure_reason or "Automatic execution failed",
                now=now,
            )
        self.session.commit()

    def release_for_recommendation(
        self,
        service_key: str,
        recommendation_id: UUID,
        *,
        now: datetime,
        success: bool | None,
        failure_reason: str | None = None,
    ) -> None:
        reservation = self.session.scalar(
            select(AdaptiveExecutionReservationRecord).where(
                AdaptiveExecutionReservationRecord.service_key == service_key,
                AdaptiveExecutionReservationRecord.recommendation_id
                == recommendation_id,
                AdaptiveExecutionReservationRecord.active.is_(True),
            )
        )
        if reservation is None:
            return
        self.release(
            reservation.id,
            now=now,
            success=success,
            failure_reason=failure_reason,
        )

    def fail_service(
        self,
        service_key: str,
        reason: str,
        *,
        now: datetime,
        immediate: bool = False,
    ) -> None:
        state = self.lock(service_key, now=now)
        if immediate:
            state.failure_count = max(
                state.failure_count,
                self.config.failure_threshold - 1,
            )
        self._fail_service(state, reason, now=now)
        self.session.commit()

    def manual_open(self, service_key: str, reason: str, *, now: datetime) -> None:
        state = self.lock(service_key, now=now)
        state.manual_disabled = True
        state.failure_count = max(
            state.failure_count,
            self.config.failure_threshold,
        )
        state.last_failure_reason = reason[:1000]
        state.opened_at = now
        state.next_attempt_at = recovery_deadline(
            now,
            self.config.recovery_timeout_seconds,
        )
        self._transition(
            state,
            BreakerState.OPEN.value,
            reason,
            "administrator",
            now,
        )
        self.session.commit()

    def request_recovery(
        self,
        service_key: str,
        *,
        clear_manual_disable: bool,
        now: datetime,
    ) -> AdaptiveControlBreakerRecord:
        state = self.lock(service_key, now=now)
        global_control = self.session.get(ExecutionGlobalControlRecord, "global")
        service_control = self.session.get(
            ExecutionServiceControlRecord,
            service_key,
        )
        if global_control is not None and global_control.kill_switch_active:
            self.session.rollback()
            raise BreakerRejected(
                "Global emergency kill switch overrides breaker recovery"
            )
        if service_control is not None and service_control.manual_override:
            self.session.rollback()
            raise BreakerRejected(
                "Per-service manual override overrides breaker recovery"
            )
        if state.manual_disabled and not clear_manual_disable:
            self.session.rollback()
            raise BreakerRejected(
                "Manual disable is active; explicit administrator release is required"
            )
        if state.state != BreakerState.OPEN.value:
            self.session.rollback()
            raise BreakerRejected("Only an OPEN breaker can request recovery")
        if not recovery_ready(
            state=state.state,
            next_attempt_at=state.next_attempt_at,
            now=now,
        ):
            self.session.rollback()
            raise BreakerRejected("Circuit breaker recovery timeout has not elapsed")
        if self.session.scalar(
            select(AdaptiveExecutionReservationRecord.id).where(
                AdaptiveExecutionReservationRecord.service_key == service_key,
                AdaptiveExecutionReservationRecord.active.is_(True),
            )
        ):
            self.session.rollback()
            raise BreakerRejected("An adaptive execution reservation is active")
        state.manual_disabled = False
        state.success_count = 0
        state.half_open_attempts = 0
        state.next_attempt_at = None
        self._transition(
            state,
            BreakerState.HALF_OPEN.value,
            "Administrator requested controlled recovery",
            "administrator",
            now,
        )
        self.session.commit()
        self.session.refresh(state)
        return state

    def report_component(
        self,
        service_key: str,
        component: str,
        *,
        healthy: bool,
        reason: str,
        failure_threshold: int,
        now: datetime,
    ) -> ComponentHealthBreakerRecord:
        record = self.session.scalar(
            select(ComponentHealthBreakerRecord)
            .where(
                ComponentHealthBreakerRecord.service_key == service_key,
                ComponentHealthBreakerRecord.component == component,
            )
            .with_for_update()
        )
        if record is None:
            record = ComponentHealthBreakerRecord(
                id=uuid4(),
                service_key=service_key,
                component=component,
                state=BreakerState.CLOSED.value,
                failure_count=0,
                last_failure_reason=None,
                next_attempt_at=None,
                updated_at=now,
            )
            self.session.add(record)
        if (
            not healthy
            and record.state == BreakerState.OPEN.value
            and record.last_failure_reason == reason[:1000]
        ):
            return record
        if healthy:
            record.failure_count = 0
            record.last_failure_reason = None
            record.next_attempt_at = None
            record.state = BreakerState.CLOSED.value
        else:
            record.failure_count += 1
            record.last_failure_reason = reason[:1000]
            if record.failure_count >= failure_threshold:
                record.state = BreakerState.OPEN.value
                record.next_attempt_at = recovery_deadline(
                    now,
                    self.config.recovery_timeout_seconds,
                )
        record.updated_at = now
        self.session.commit()
        self.session.refresh(record)
        return record

    def _fail_service(
        self,
        state: AdaptiveControlBreakerRecord,
        reason: str,
        *,
        now: datetime,
    ) -> None:
        if (
            state.state == BreakerState.OPEN.value
            and state.last_failure_reason == reason[:1000]
        ):
            return
        state.failure_count += 1
        state.success_count = 0
        state.half_open_attempts = 0
        state.last_failure_reason = reason[:1000]
        if (
            state.state == BreakerState.HALF_OPEN.value
            or state.failure_count >= self.config.failure_threshold
        ):
            state.opened_at = now
            state.next_attempt_at = recovery_deadline(
                now,
                self.config.recovery_timeout_seconds,
            )
            self._transition(
                state,
                BreakerState.OPEN.value,
                reason,
                "automatic",
                now,
            )

    def _transition(
        self,
        state: AdaptiveControlBreakerRecord,
        new_state: str,
        reason: str,
        actor: str,
        now: datetime,
    ) -> None:
        if state.state == new_state and actor != "administrator":
            state.updated_at = now
            return
        self.session.add(
            CircuitBreakerEventRecord(
                id=uuid4(),
                service_key=state.service_key,
                from_state=state.state,
                to_state=new_state,
                reason=reason[:2000],
                actor=actor,
                created_at=now,
            )
        )
        state.state = new_state
        state.updated_at = now
