from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.circuit_breaker.repository import BreakerRepository
from app.circuit_breaker.metrics import publish_breaker_state
from app.circuit_breaker.validation_rules import telemetry_is_fresh
from app.telemetry.models import PolicyExecutionRecord, PolicyRollbackEventRecord
from app.storage.repositories import TelemetryRepository


class HealthEvaluator:
    def __init__(self, settings) -> None:
        self.settings = settings

    def evaluate(
        self,
        service_key: str,
        *,
        session: Session,
        now: datetime | None = None,
    ) -> list[str]:
        current_time = now or datetime.now(timezone.utc)
        repository = BreakerRepository(session, self.settings)
        failures: list[str] = []
        latest = TelemetryRepository(session).latest(service_key)
        fresh = telemetry_is_fresh(
            latest,
            now=current_time,
            maximum_age_seconds=self.settings.breaker_telemetry_max_age_seconds,
        )
        repository.report_component(
            service_key,
            "TELEMETRY",
            healthy=fresh,
            reason="Telemetry is missing, invalid, or stale",
            failure_threshold=1,
            now=current_time,
        )
        if not fresh:
            failures.append("Telemetry is missing, invalid, or stale")
            repository.fail_service(
                service_key,
                "Telemetry is missing, invalid, or stale",
                now=current_time,
                immediate=True,
            )

        rollback_count = int(
            session.scalar(
                select(func.count(PolicyRollbackEventRecord.id)).where(
                    PolicyRollbackEventRecord.service_key == service_key,
                    PolicyRollbackEventRecord.created_at
                    >= current_time
                    - timedelta(
                        seconds=self.settings.breaker_rollback_window_seconds
                    ),
                    PolicyRollbackEventRecord.status.in_(
                        ("POLICY_RESTORED", "REDIS_SYNCED", "COMPLETED")
                    ),
                )
            )
            or 0
        )
        if rollback_count >= self.settings.breaker_rollback_limit:
            reason = "Rollback frequency exceeded the configured limit"
            failures.append(reason)
            repository.fail_service(
                service_key,
                reason,
                now=current_time,
                immediate=True,
            )

        active = session.scalar(
            select(PolicyExecutionRecord).where(
                PolicyExecutionRecord.service_key == service_key,
                PolicyExecutionRecord.status == "SUBMITTED",
            )
        )
        if (
            active is not None
            and active.started_at is not None
            and (_aware(current_time) - _aware(active.started_at)).total_seconds()
            >= self.settings.rollback_redis_sync_timeout_seconds
        ):
            reason = "Redis policy synchronization exceeded its timeout"
            failures.append(reason)
            repository.report_component(
                service_key,
                "REDIS_SYNC",
                healthy=False,
                reason=reason,
                failure_threshold=1,
                now=current_time,
            )
            repository.fail_service(
                service_key,
                reason,
                now=current_time,
                immediate=True,
            )
        state = repository.get(service_key, now=current_time)
        publish_breaker_state(service_key, state.state)
        return failures


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value
