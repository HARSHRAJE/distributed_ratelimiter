import logging
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy.orm import Session

from app.config import Settings
from app.execution.execution_repository import ExecutionRepository
from app.rollback.policy_client import PolicyClient, PolicyClientError
from app.forecasting.metrics import ROLLBACK_FAILURES
from app.rollback.health_monitor import HealthMonitor
from app.rollback.rollback_decision_engine import RollbackDecisionEngine
from app.rollback.rollback_repository import RollbackRepository
from app.rollback.schemas import (
    RollbackEvaluation,
    RollbackEvent,
    RollbackHistory,
    RollbackTrigger,
)
from app.telemetry.models import PolicyExecutionRecord, PolicyRollbackEventRecord


logger = logging.getLogger(__name__)


class RollbackError(RuntimeError):
    pass


class RollbackService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def evaluate(
        self,
        service_key: str,
        *,
        session: Session,
        now: datetime | None = None,
    ) -> RollbackEvaluation:
        current_time = now or datetime.now(timezone.utc)
        repository = RollbackRepository(session)
        execution = repository.latest_execution(service_key)
        if execution is None:
            return self._evaluation(
                service_key,
                None,
                eligible=False,
                triggers=[],
                message="No policy execution is available for rollback",
                now=current_time,
            )
        existing = repository.for_execution(execution.id)
        if existing is not None:
            is_pending = existing.status in (
                "DETECTED",
                "INITIATED",
                "POLICY_RESTORED",
                "REDIS_SYNCED",
            )
            return self._evaluation(
                service_key,
                execution.id,
                eligible=is_pending,
                triggers=[
                    RollbackTrigger(
                        metric=existing.trigger_metric,
                        value=float(existing.trigger_value),
                        threshold=float(existing.threshold_value),
                        reason=existing.reason,
                    )
                ] if is_pending else [],
                message=f"Rollback event is {existing.status}",
                now=current_time,
            )
        if execution.status not in ("APPLIED", "SUBMITTED"):
            return self._evaluation(
                service_key,
                execution.id,
                eligible=False,
                triggers=[],
                message="Latest execution is not eligible for rollback",
                now=current_time,
            )

        since = (
            execution.completed_at
            if execution.status == "APPLIED" and execution.completed_at
            else execution.started_at
        )
        monitor = HealthMonitor(session)
        windows = monitor.windows_since(service_key, since)
        if execution.status == "SUBMITTED":
            decision = RollbackDecisionEngine(self.settings).decide(
                execution,
                windows,
                baseline=None,
                now=current_time,
            )
            return self._evaluation(
                service_key,
                execution.id,
                eligible=decision.eligible,
                triggers=decision.triggers,
                message=decision.message,
                now=current_time,
                triggered=decision.triggered,
            )

        latest = windows[-1] if windows else None
        if latest is None or latest.data_quality != "valid":
            return self._evaluation(
                service_key,
                execution.id,
                eligible=False,
                triggers=[],
                message="Fresh valid telemetry is unavailable",
                now=current_time,
            )
        age = (current_time - _utc(latest.window_start)).total_seconds()
        if age < 0 or age > self.settings.rollback_telemetry_max_age_seconds:
            return self._evaluation(
                service_key,
                execution.id,
                eligible=False,
                triggers=[],
                message="Telemetry is stale or future-dated",
                now=current_time,
            )
        baseline = monitor.latest_before(service_key, execution.started_at)
        decision = RollbackDecisionEngine(self.settings).decide(
            execution,
            windows,
            baseline=baseline,
            now=current_time,
        )
        return self._evaluation(
            service_key,
            execution.id,
            eligible=decision.eligible,
            triggers=decision.triggers,
            message=decision.message,
            now=current_time,
            triggered=decision.triggered,
        )

    def execute(
        self,
        execution_id: UUID,
        *,
        session: Session,
        now: datetime | None = None,
    ) -> RollbackEvent:
        current_time = now or datetime.now(timezone.utc)
        rollback_repository = RollbackRepository(session)
        execution = rollback_repository.execution(execution_id)
        if execution is None:
            raise RollbackError("Execution not found")
        client = PolicyClient(self.settings)
        event = rollback_repository.for_execution(execution_id)
        if event is None:
            evaluation = self.evaluate(
                execution.service_key,
                session=session,
                now=current_time,
            )
            if not evaluation.triggered or not evaluation.triggers:
                raise RollbackError(evaluation.message)
            attempts = rollback_repository.attempt_count_since(
                execution.service_key,
                current_time - timedelta(hours=1),
            )
            if attempts >= self.settings.rollback_max_attempts_per_hour:
                reason = (
                    "Maximum rollback attempts per hour reached; "
                    "operator review required"
                )
                trigger = evaluation.triggers[0]
                event, _ = rollback_repository.begin(
                    execution,
                    metric=trigger.metric,
                    value=trigger.value,
                    threshold=trigger.threshold,
                    reason=trigger.reason,
                    now=current_time,
                )
                event = rollback_repository.update(
                    event,
                    status="FAILED",
                    completed_at=current_time,
                    reason=reason,
                )
                execution_repository = ExecutionRepository(session)
                execution_repository.pause_service(
                    execution.service_key,
                    reason=reason,
                    now=current_time,
                )
                execution_repository.update(
                    execution,
                    status="FAILED",
                    failure_reason=reason,
                    completed_at=current_time,
                )
                self._alert(execution.service_key, "ATTEMPT_LIMIT")
                return RollbackEvent.model_validate(event)
            trigger = evaluation.triggers[0]
            if execution.status == "SUBMITTED" and execution.resulting_version is None:
                ExecutionRepository(session).pause_service(
                    execution.service_key,
                    reason=(
                        "Redis synchronization timed out; confirming Policy "
                        "Service execution before rollback"
                    ),
                    now=current_time,
                )
                service = client.get_service(execution.service_key)
                accepted = client.execution_status(service.id, execution.id)
                if (
                    not accepted.accepted
                    or accepted.resulting_version is None
                    or accepted.resulting_rate is None
                ):
                    raise RollbackError(
                        "Policy Service has not confirmed the timed-out execution"
                    )
                if (
                    service.config_version != accepted.resulting_version
                    or abs(
                        service.global_refill_rate
                        - accepted.resulting_rate
                    ) > 0.001
                    or abs(
                        accepted.resulting_rate - execution.proposed_rate
                    ) > 0.001
                ):
                    raise RollbackError(
                        "Active service configuration no longer matches the "
                        "timed-out execution; concurrent change was preserved"
                    )
                execution.resulting_version = accepted.resulting_version
                session.commit()
            event, _ = rollback_repository.begin(
                execution,
                metric=trigger.metric,
                value=trigger.value,
                threshold=trigger.threshold,
                reason=trigger.reason,
                now=current_time,
            )
            ExecutionRepository(session).pause_service(
                execution.service_key,
                reason=f"Automatic control paused after rollback trigger: {trigger.metric}",
                now=current_time,
            )
        if event.status == "COMPLETED":
            return RollbackEvent.model_validate(event)
        if event.status == "FAILED":
            raise RollbackError(event.reason)
        return self._advance(
            event,
            execution,
            rollback_repository=rollback_repository,
            execution_repository=ExecutionRepository(session),
            client=client,
            now=current_time,
        )

    def get(
        self,
        rollback_id: UUID,
        *,
        session: Session,
    ) -> RollbackEvent:
        event = RollbackRepository(session).get(rollback_id)
        if event is None:
            raise RollbackError("Rollback event not found")
        return RollbackEvent.model_validate(event)

    @staticmethod
    def history(
        service_key: str,
        *,
        session: Session,
        limit: int,
    ) -> RollbackHistory:
        events = RollbackRepository(session).history(
            service_key,
            limit=limit,
        )
        return RollbackHistory(
            service_key=service_key,
            rollbacks=[
                RollbackEvent.model_validate(event) for event in events
            ],
        )

    def ensure_resume_allowed(
        self,
        service_key: str,
        *,
        session: Session,
        manual_approval: bool = False,
        now: datetime | None = None,
    ) -> None:
        current_time = now or datetime.now(timezone.utc)
        repository = RollbackRepository(session)
        latest_event = repository.latest_event(service_key)
        if latest_event is None:
            return
        if latest_event.status not in ("COMPLETED", "FAILED"):
            raise RollbackError(
                "A rollback is still in progress; adaptive control remains paused"
            )
        if latest_event.status == "FAILED" and not manual_approval:
            raise RollbackError(
                "A failed rollback requires explicit administrator approval before re-enabling"
            )
        if latest_event.completed_at is None:
            raise RollbackError("Rollback completion time is unavailable")
        elapsed = (current_time - _utc(latest_event.completed_at)).total_seconds()
        if elapsed < self.settings.rollback_cooldown_seconds:
            raise RollbackError(
                "Rollback cooldown has not elapsed; adaptive control remains paused"
            )
        windows = HealthMonitor(session).windows_since(
            service_key,
            latest_event.completed_at,
            limit=max(100, self.settings.rollback_minimum_healthy_windows),
        )
        required = self.settings.rollback_minimum_healthy_windows
        selected = windows[-required:]
        if len(selected) < required or any(
            item.data_quality != "valid" for item in selected
        ):
            raise RollbackError(
                "A minimum healthy observation period is required before re-enabling"
            )
        if (
            (current_time - _utc(selected[-1].window_start)).total_seconds()
            > self.settings.rollback_telemetry_max_age_seconds
        ):
            raise RollbackError(
                "Fresh telemetry is required before re-enabling adaptive control"
            )
        for item in selected:
            error_percent = _error_percent(
                item.error_rate,
                item.incoming_rps,
            )
            if (
                item.p95_latency_ms is None
                or item.p95_latency_ms > self.settings.rollback_p95_threshold_ms
                or item.cpu_utilization is None
                or item.cpu_utilization
                    > self.settings.rollback_cpu_threshold_percent
                or error_percent > self.settings.rollback_5xx_threshold_percent
                or item.queue_depth is None
                or item.queue_depth
                    > self.settings.rollback_queue_depth_threshold
            ):
                raise RollbackError(
                    "Service has not completed the required healthy observation period"
                )

    def _advance(
        self,
        event: PolicyRollbackEventRecord,
        execution: PolicyExecutionRecord,
        *,
        rollback_repository: RollbackRepository,
        execution_repository: ExecutionRepository,
        client: PolicyClient,
        now: datetime,
    ) -> RollbackEvent:
        if event.status == "DETECTED":
            event = rollback_repository.update(
                event,
                status="INITIATED",
            )
        try:
            accepted = client.rollback_status(
                client.get_service(event.service_key).id,
                event.id,
            )
            if not accepted.accepted:
                service = client.get_service(event.service_key)
                if service.config_version != event.failed_version:
                    return self._fail(
                        event,
                        execution,
                        "Active service version changed before rollback; "
                        "concurrent administrator update was preserved",
                        rollback_repository=rollback_repository,
                        execution_repository=execution_repository,
                        now=now,
                    )
                try:
                    accepted = client.rollback_service(
                        service,
                        rollback_id=event.id,
                        expected_active_version=event.failed_version,
                        restored_from_version=event.restored_from_version,
                    )
                except PolicyClientError as error:
                    if not error.ambiguous:
                        if (
                            error.status_code is None
                            or error.status_code >= 500
                        ):
                            return RollbackEvent.model_validate(event)
                        return self._fail(
                            event,
                            execution,
                            str(error),
                            rollback_repository=rollback_repository,
                            execution_repository=execution_repository,
                            now=now,
                        )
                    try:
                        accepted = client.rollback_status(service.id, event.id)
                    except PolicyClientError:
                        return RollbackEvent.model_validate(event)
                    if not accepted.accepted:
                        return RollbackEvent.model_validate(event)
            if not accepted.accepted or accepted.rollback_version is None:
                return RollbackEvent.model_validate(event)
            if accepted.rollback_version <= event.failed_version:
                return self._fail(
                    event,
                    execution,
                    "Policy Service returned a non-incrementing rollback version",
                    rollback_repository=rollback_repository,
                    execution_repository=execution_repository,
                    now=now,
                )
            if event.rollback_version is None:
                event = rollback_repository.update(
                    event,
                    status="POLICY_RESTORED",
                    rollback_version=accepted.rollback_version,
                )
            return self._verify_effective(
                event,
                execution,
                rollback_repository=rollback_repository,
                execution_repository=execution_repository,
                client=client,
                now=now,
            )
        except PolicyClientError as error:
            if (
                error.ambiguous
                or error.status_code is None
                or error.status_code >= 500
            ):
                return RollbackEvent.model_validate(event)
            return self._fail(
                event,
                execution,
                str(error),
                rollback_repository=rollback_repository,
                execution_repository=execution_repository,
                now=now,
            )

    def _verify_effective(
        self,
        event: PolicyRollbackEventRecord,
        execution: PolicyExecutionRecord,
        *,
        rollback_repository: RollbackRepository,
        execution_repository: ExecutionRepository,
        client: PolicyClient,
        now: datetime,
    ) -> RollbackEvent:
        if event.rollback_version is None:
            raise RollbackError("Rollback version is not recorded")
        try:
            effective = client.get_effective(event.service_key)
        except PolicyClientError:
            if not self._sync_timed_out(event, now):
                return RollbackEvent.model_validate(event)
            return self._fail(
                event,
                execution,
                "Policy Service could not provide the effective configuration "
                "within the rollback synchronization timeout",
                rollback_repository=rollback_repository,
                execution_repository=execution_repository,
                now=now,
            )
        if effective.config_version < event.rollback_version:
            if self._sync_timed_out(event, now):
                return self._fail(
                    event,
                    execution,
                    "Redis did not synchronize the rollback policy within "
                    "the configured timeout",
                    rollback_repository=rollback_repository,
                    execution_repository=execution_repository,
                    now=now,
                )
            return RollbackEvent.model_validate(event)
        if effective.config_version > event.rollback_version:
            return self._fail(
                event,
                execution,
                "Effective service version advanced after rollback; "
                "concurrent update was preserved",
                rollback_repository=rollback_repository,
                execution_repository=execution_repository,
                now=now,
            )
        expected_rate = float(execution.previous_rate)
        if abs(effective.global_refill_rate - expected_rate) > 0.001:
            return self._fail(
                event,
                execution,
                "Effective Redis rate does not match the restored service version",
                rollback_repository=rollback_repository,
                execution_repository=execution_repository,
                now=now,
            )
        if event.status != "REDIS_SYNCED":
            event = rollback_repository.update(
                event,
                status="REDIS_SYNCED",
                effective_config_verified_at=now,
            )
        verified_at = _utc(event.effective_config_verified_at or now)
        if (
            (now - verified_at).total_seconds()
            < self.settings.gateway_policy_cache_ttl_seconds
        ):
            return RollbackEvent.model_validate(event)
        event = rollback_repository.update(
            event,
            status="COMPLETED",
            completed_at=now,
        )
        execution_repository.update(
            execution,
            status="ROLLED_BACK",
            resulting_version=event.rollback_version,
            failure_reason=None,
            completed_at=now,
        )
        return RollbackEvent.model_validate(event)

    def _sync_timed_out(
        self,
        event: PolicyRollbackEventRecord,
        now: datetime,
    ) -> bool:
        return (
            now - _utc(event.created_at)
        ).total_seconds() >= self.settings.rollback_redis_sync_timeout_seconds

    def _fail(
        self,
        event: PolicyRollbackEventRecord,
        execution: PolicyExecutionRecord,
        reason: str,
        *,
        rollback_repository: RollbackRepository,
        execution_repository: ExecutionRepository,
        now: datetime,
    ) -> RollbackEvent:
        event = rollback_repository.update(
            event,
            status="FAILED",
            completed_at=now,
            reason=reason[:4000],
        )
        execution_repository.pause_service(
            execution.service_key,
            reason="Rollback failed; operator review required",
            now=now,
        )
        execution_repository.update(
            execution,
            status="FAILED",
            failure_reason=reason[:4000],
            completed_at=now,
        )
        self._alert(execution.service_key, event.trigger_metric)
        return RollbackEvent.model_validate(event)

    @staticmethod
    def _alert(service_key: str, reason: str) -> None:
        ROLLBACK_FAILURES.labels(
            service_key=service_key,
            reason=reason[:50],
        ).inc()
        logger.error(
            "Policy rollback failed or needs operator review for service %s: %s",
            service_key,
            reason,
        )

    @staticmethod
    def _evaluation(
        service_key: str,
        execution_id: UUID | None,
        *,
        eligible: bool,
        triggers: list[RollbackTrigger],
        message: str,
        now: datetime,
        triggered: bool | None = None,
    ) -> RollbackEvaluation:
        return RollbackEvaluation(
            service_key=service_key,
            execution_id=execution_id,
            eligible=eligible,
            triggered=bool(triggers) if triggered is None else triggered,
            triggers=triggers,
            message=message,
            evaluated_at=now,
        )


def _error_percent(error_rps: float | None, incoming_rps: float | None) -> float:
    if error_rps is None or incoming_rps is None or incoming_rps <= 0:
        return 0.0
    return float(error_rps) / float(incoming_rps) * 100


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def scheduled_rollback_cycle(settings: Settings, session_factory) -> None:
    if len(settings.policy_service_api_key) < 32:
        logger.error(
            "Automatic rollback monitoring requires a configured Policy Service API key"
        )
        return
    for service_key in settings.service_keys:
        try:
            with session_factory() as session:
                service = RollbackService(settings)
                latest_execution = RollbackRepository(session).latest_execution(
                    service_key
                )
                if (
                    latest_execution is not None
                    and latest_execution.status == "SUBMITTED"
                ):
                    try:
                        from app.execution.execution_service import (
                            ExecutionService,
                        )

                        ExecutionService(settings).get_status(
                            latest_execution.id,
                            session=session,
                        )
                    except PolicyClientError as error:
                        logger.warning(
                            "Could not reconcile pending service execution "
                            "before rollback evaluation service=%s "
                            "error_type=%s",
                            service_key,
                            type(error).__name__,
                        )
                evaluation = service.evaluate(
                    service_key,
                    session=session,
                )
                if evaluation.triggered and evaluation.execution_id is not None:
                    event = service.execute(
                        evaluation.execution_id,
                        session=session,
                    )
                    logger.warning(
                        "Rollback state service=%s execution=%s status=%s metric=%s",
                        service_key,
                        evaluation.execution_id,
                        event.status,
                        evaluation.triggers[0].metric
                        if evaluation.triggers
                        else "pending",
                    )
        except Exception as error:
            ROLLBACK_FAILURES.labels(
                service_key=service_key,
                reason="SCHEDULER",
            ).inc()
            logger.exception(
                "Scheduled rollback evaluation failed for service=%s "
                "error_type=%s",
                service_key,
                type(error).__name__,
            )
