from datetime import datetime, timezone

from sqlalchemy.orm import Session, sessionmaker

from app.circuit_breaker.health_evaluator import HealthEvaluator
from app.circuit_breaker.metrics import publish_breaker_state
from app.circuit_breaker.repository import BreakerRepository
from app.circuit_breaker.schemas import (
    BreakerEvent,
    BreakerHistory,
    BreakerStatus,
    ComponentHealth,
)
from app.execution.policy_client import PolicyClient, PolicyClientError
from app.forecasting.forecast_service import ForecastService


class BreakerService:
    def __init__(self, settings) -> None:
        self.settings = settings

    def status(
        self,
        service_key: str,
        *,
        session: Session,
        now: datetime | None = None,
    ) -> BreakerStatus:
        current_time = now or datetime.now(timezone.utc)
        checks = HealthEvaluator(self.settings).evaluate(
            service_key,
            session=session,
            now=current_time,
        )
        repository = BreakerRepository(session, self.settings)
        record = repository.get(service_key, now=current_time)
        publish_breaker_state(service_key, record.state)
        return BreakerStatus(
            service_key=record.service_key,
            state=record.state,
            failure_count=record.failure_count,
            success_count=record.success_count,
            opened_at=record.opened_at,
            next_attempt_at=record.next_attempt_at,
            last_failure_reason=record.last_failure_reason,
            manual_disabled=record.manual_disabled,
            components=[
                ComponentHealth.model_validate(component)
                for component in repository.components(service_key)
            ],
            checks=checks,
            updated_at=record.updated_at,
        )

    def manual_open(
        self,
        service_key: str,
        reason: str,
        *,
        session: Session,
        now: datetime | None = None,
    ) -> BreakerStatus:
        current_time = now or datetime.now(timezone.utc)
        repository = BreakerRepository(session, self.settings)
        repository.manual_open(service_key, reason, now=current_time)
        return self.status(service_key, session=session, now=current_time)

    def request_recovery(
        self,
        service_key: str,
        *,
        clear_manual_disable: bool,
        session: Session,
        session_factory: sessionmaker,
        now: datetime | None = None,
    ) -> BreakerStatus:
        current_time = now or datetime.now(timezone.utc)
        checks = HealthEvaluator(self.settings).evaluate(
            service_key,
            session=session,
            now=current_time,
        )
        if checks:
            raise ValueError(
                "Recovery checks failed: " + "; ".join(checks)
            )
        repository = BreakerRepository(session, self.settings)
        try:
            ForecastService(self.settings, session_factory).evaluate(service_key)
        except ValueError as error:
            repository.report_component(
                service_key,
                "FORECASTING",
                healthy=False,
                reason=f"Forecast recovery check failed: {error}",
                failure_threshold=self.settings.breaker_forecast_failure_threshold,
                now=current_time,
            )
            raise ValueError(f"Forecast recovery check failed: {error}") from error

        client = PolicyClient(self.settings)
        try:
            service = client.get_service(service_key)
        except PolicyClientError as error:
            repository.report_component(
                service_key,
                "POLICY_SERVICE",
                healthy=False,
                reason=str(error),
                failure_threshold=self.settings.breaker_policy_failure_threshold,
                now=current_time,
            )
            raise
        repository.report_component(
            service_key,
            "POLICY_SERVICE",
            healthy=True,
            reason="Policy Service recovery check succeeded",
            failure_threshold=self.settings.breaker_policy_failure_threshold,
            now=current_time,
        )
        try:
            effective = client.get_effective(service_key)
        except PolicyClientError as error:
            repository.report_component(
                service_key,
                "REDIS_SYNC",
                healthy=False,
                reason=str(error),
                failure_threshold=self.settings.breaker_redis_failure_threshold,
                now=current_time,
            )
            raise
        if effective.config_version != service.config_version:
            reason = "Effective Redis policy version differs from Policy Service"
            repository.report_component(
                service_key,
                "REDIS_SYNC",
                healthy=False,
                reason=reason,
                failure_threshold=self.settings.breaker_redis_failure_threshold,
                now=current_time,
            )
            raise ValueError(reason)
        repository.report_component(
            service_key,
            "REDIS_SYNC",
            healthy=True,
            reason="Effective policy synchronization recovery check succeeded",
            failure_threshold=self.settings.breaker_redis_failure_threshold,
            now=current_time,
        )
        repository.report_component(
            service_key,
            "EXECUTION",
            healthy=True,
            reason="Controller health checks succeeded before recovery",
            failure_threshold=self.settings.breaker_execution_failure_threshold,
            now=current_time,
        )
        unhealthy = [
            item.component
            for item in repository.components(service_key)
            if item.state != "CLOSED"
        ]
        if unhealthy:
            raise ValueError(
                "Component recovery is incomplete: " + ", ".join(unhealthy)
            )
        repository.request_recovery(
            service_key,
            clear_manual_disable=clear_manual_disable,
            now=current_time,
        )
        return self.status(service_key, session=session, now=current_time)

    @staticmethod
    def history(
        service_key: str,
        *,
        session: Session,
        settings,
        limit: int,
    ) -> BreakerHistory:
        events = BreakerRepository(session, settings).events(
            service_key,
            limit=limit,
        )
        return BreakerHistory(
            service_key=service_key,
            events=[BreakerEvent.model_validate(event) for event in events],
        )
