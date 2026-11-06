from datetime import datetime
from uuid import UUID

from sqlalchemy.orm import Session

from app.circuit_breaker.health_evaluator import HealthEvaluator
from app.circuit_breaker.metrics import publish_breaker_state
from app.circuit_breaker.repository import BreakerRejected, BreakerRepository
from app.circuit_breaker.schemas import ExecutionReservation


class ExecutionGuard:
    def __init__(self, settings) -> None:
        self.settings = settings

    def reserve(
        self,
        *,
        service_key: str,
        recommendation_id: UUID,
        action: str,
        current_rate: float,
        proposed_rate: float,
        session: Session,
        now: datetime,
    ) -> ExecutionReservation:
        HealthEvaluator(self.settings).evaluate(
            service_key,
            session=session,
            now=now,
        )
        try:
            reservation = BreakerRepository(
                session,
                self.settings,
            ).reserve(
                service_key=service_key,
                recommendation_id=recommendation_id,
                action=action,
                current_rate=current_rate,
                proposed_rate=proposed_rate,
                now=now,
            )
        except BreakerRejected:
            raise
        breaker = BreakerRepository(
            session,
            self.settings,
        ).get(service_key, now=now)
        publish_breaker_state(service_key, breaker.state)
        return ExecutionReservation.model_validate(reservation)

    def release(
        self,
        reservation_id: UUID,
        *,
        session: Session,
        now: datetime,
        success: bool | None,
        failure_reason: str | None = None,
    ) -> None:
        BreakerRepository(session, self.settings).release(
            reservation_id,
            now=now,
            success=success,
            failure_reason=failure_reason,
        )
        breaker = BreakerRepository(
            session,
            self.settings,
        ).get_for_service_reservation(reservation_id, now=now)
        if breaker is not None:
            publish_breaker_state(breaker.service_key, breaker.state)

    def report_component(
        self,
        service_key: str,
        component: str,
        *,
        healthy: bool,
        reason: str,
        failure_threshold: int,
        session: Session,
        now: datetime,
    ) -> None:
        BreakerRepository(session, self.settings).report_component(
            service_key,
            component,
            healthy=healthy,
            reason=reason,
            failure_threshold=failure_threshold,
            now=now,
        )
