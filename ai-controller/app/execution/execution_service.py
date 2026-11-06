from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.circuit_breaker.execution_guard import ExecutionGuard
from app.circuit_breaker.repository import BreakerRejected, BreakerRepository
from app.config import Settings
from app.execution.eligibility_checker import EligibilityChecker
from app.execution.execution_coordinator import ExecutionCoordinator
from app.execution.execution_repository import ExecutionRepository
from app.execution.policy_client import PolicyClient, PolicyClientError
from app.execution.rollout_manager import RolloutManager
from app.execution.schemas import ExecutionCheck, ExecutionResult
from app.storage.repositories import (
    RecommendationRepository,
    RecommendationValidationRepository,
    TelemetryRepository,
)
from app.telemetry.models import ShadowEvaluationRecord


class ExecutionRejected(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        checks: list[ExecutionCheck] | None = None,
    ) -> None:
        super().__init__(message)
        self.checks = checks or []


class ExecutionService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def execute(
        self,
        recommendation_id: UUID,
        *,
        session: Session,
        now: datetime | None = None,
    ) -> ExecutionResult:
        current_time = now or datetime.now(timezone.utc)
        recommendation = RecommendationRepository(session).get(
            recommendation_id
        )
        if recommendation is None:
            raise ExecutionRejected("Recommendation not found")
        repository = ExecutionRepository(session)
        client = PolicyClient(self.settings)
        coordinator = ExecutionCoordinator(
            client,
            repository,
            RolloutManager(self.settings),
            self.settings.gateway_policy_cache_ttl_seconds,
            self.settings,
        )
        active = repository.active_for_service(recommendation.service_key)
        if active is not None:
            if active.recommendation_id != recommendation.id:
                raise ExecutionRejected(
                    "Another policy execution is still pending"
                )
            if active.status == "SUBMITTED":
                try:
                    active = coordinator.verify_effective(active)
                except PolicyClientError as error:
                    ExecutionGuard(self.settings).report_component(
                        recommendation.service_key,
                        "POLICY_SERVICE",
                        healthy=False,
                        reason=str(error),
                        failure_threshold=(
                            self.settings.breaker_policy_failure_threshold
                        ),
                        session=session,
                        now=current_time,
                    )
                    raise
                if active.status == "APPLIED":
                    BreakerRepository(session, self.settings).release_for_recommendation(
                        recommendation.service_key,
                        recommendation.id,
                        now=current_time,
                        success=True,
                    )
                    self._report_execution_health(
                        recommendation.service_key,
                        session=session,
                        now=current_time,
                        applied=True,
                        reason="Effective policy synchronized",
                    )
                elif active.status == "FAILED":
                    BreakerRepository(session, self.settings).release_for_recommendation(
                        recommendation.service_key,
                        recommendation.id,
                        now=current_time,
                        success=False,
                        failure_reason=active.failure_reason,
                    )
                return _result(active)

        guard = ExecutionGuard(self.settings)
        try:
            reservation = guard.reserve(
                service_key=recommendation.service_key,
                recommendation_id=recommendation.id,
                action=recommendation.action,
                current_rate=float(recommendation.current_rate),
                proposed_rate=float(recommendation.recommended_rate),
                session=session,
                now=current_time,
            )
        except BreakerRejected as error:
            raise ExecutionRejected(str(error)) from error
        result: ExecutionResult | None = None
        failure_reason: str | None = None
        try:
            result = self._execute_inner(
                recommendation_id,
                session=session,
                now=current_time,
            )
            if result.status == "APPLIED":
                self._report_execution_health(
                    recommendation.service_key,
                    session=session,
                    now=current_time,
                    applied=True,
                    reason="Execution and effective policy verification succeeded",
                )
            elif result.status == "FAILED":
                failure_reason = result.failure_reason or "Execution failed"
                self._report_execution_health(
                    recommendation.service_key,
                    session=session,
                    now=current_time,
                    applied=False,
                    reason=failure_reason,
                )
            return result
        except PolicyClientError as error:
            failure_reason = str(error)
            guard.report_component(
                recommendation.service_key,
                "POLICY_SERVICE",
                healthy=False,
                reason=failure_reason,
                failure_threshold=self.settings.breaker_policy_failure_threshold,
                session=session,
                now=current_time,
            )
            raise
        except ExecutionRejected as error:
            failure_reason = str(error)
            raise
        finally:
            if result is None or (
                result is not None and result.status in {"APPLIED", "FAILED"}
            ):
                guard.release(
                    reservation.id,
                    session=session,
                    now=current_time,
                    success=(
                        True
                        if result is not None and result.status == "APPLIED"
                        else False
                        if result is not None and result.status == "FAILED"
                        else None
                    ),
                    failure_reason=failure_reason,
                )

    def _execute_inner(
        self,
        recommendation_id: UUID,
        *,
        session: Session,
        now: datetime,
    ) -> ExecutionResult:
        current_time = now
        recommendation = RecommendationRepository(session).get(
            recommendation_id
        )
        if recommendation is None:
            raise ExecutionRejected("Recommendation not found")
        repository = ExecutionRepository(session)
        client = PolicyClient(self.settings)
        coordinator = ExecutionCoordinator(
            client,
            repository,
            RolloutManager(self.settings),
            self.settings.gateway_policy_cache_ttl_seconds,
            self.settings,
        )
        active = repository.active_for_service(recommendation.service_key)
        if active is not None:
            if active.recommendation_id != recommendation.id:
                raise ExecutionRejected(
                    "Another policy execution is still pending"
                )
            if active.status in ("PENDING", "VALIDATING"):
                active = repository.update(active, status="VALIDATING")
                active = coordinator.submit_or_resume(
                    active,
                    client.get_service(active.service_key),
                )
            if active.status == "SUBMITTED":
                active = coordinator.verify_effective(active)
            return _result(active)

        service = client.get_service(recommendation.service_key)
        validation = RecommendationValidationRepository(session).latest(
            recommendation_id
        )
        telemetry = TelemetryRepository(session).latest(
            recommendation.service_key
        )
        control = repository.control(recommendation.service_key)
        shadow = session.scalar(
            select(ShadowEvaluationRecord)
            .where(
                ShadowEvaluationRecord.recommendation_id == recommendation_id
            )
            .order_by(ShadowEvaluationRecord.created_at.desc())
            .limit(1)
        )
        checks = EligibilityChecker(self.settings).check(
            recommendation=recommendation,
            validation=validation,
            shadow=shadow,
            telemetry=telemetry,
            control=control,
            service=service,
            repository=repository,
            global_kill_switch_active=repository.global_kill_switch_active(),
            now=current_time,
        )
        failed_checks = [check for check in checks if not check.passed]
        if failed_checks:
            if any(
                check.check == "TELEMETRY_FRESHNESS"
                for check in failed_checks
            ):
                RolloutManager(self.settings).pause(
                    recommendation.service_key,
                    "Telemetry is missing, invalid, or stale",
                    repository=repository,
                    now=current_time,
                )
            raise ExecutionRejected(
                "Recommendation failed execution eligibility",
                checks=checks,
            )

        record, created = repository.begin(
            recommendation_id=recommendation.id,
            service_key=recommendation.service_key,
            previous_version=service.config_version,
            previous_rate=service.global_refill_rate,
            proposed_rate=float(recommendation.recommended_rate),
            started_at=current_time,
        )
        if not created and record.recommendation_id != recommendation.id:
            raise ExecutionRejected(
                "Another policy execution is still pending"
            )
        if record.status in ("PENDING", "VALIDATING"):
            record = repository.update(record, status="VALIDATING")
            service = client.get_service(record.service_key)
            record = coordinator.submit_or_resume(record, service)
        if record.status == "SUBMITTED":
            record = coordinator.verify_effective(record)
        return _result(record, checks)

    def _report_execution_health(
        self,
        service_key: str,
        *,
        session: Session,
        now: datetime,
        applied: bool,
        reason: str,
    ) -> None:
        guard = ExecutionGuard(self.settings)
        guard.report_component(
            service_key,
            "EXECUTION",
            healthy=applied,
            reason=reason,
            failure_threshold=self.settings.breaker_execution_failure_threshold,
            session=session,
            now=now,
        )
        if applied:
            guard.report_component(
                service_key,
                "REDIS_SYNC",
                healthy=True,
                reason=reason,
                failure_threshold=self.settings.breaker_redis_failure_threshold,
                session=session,
                now=now,
            )
            guard.report_component(
                service_key,
                "POLICY_SERVICE",
                healthy=True,
                reason=reason,
                failure_threshold=self.settings.breaker_policy_failure_threshold,
                session=session,
                now=now,
            )

    def get_status(
        self,
        execution_id: UUID,
        *,
        session: Session,
    ) -> ExecutionResult:
        repository = ExecutionRepository(session)
        record = repository.get(execution_id)
        if record is None:
            raise ExecutionRejected("Execution not found")
        if record.status == "SUBMITTED":
            client = PolicyClient(self.settings)
            record = ExecutionCoordinator(
                client,
                repository,
                RolloutManager(self.settings),
                self.settings.gateway_policy_cache_ttl_seconds,
                self.settings,
            ).verify_effective(record)
        return _result(record)

    @staticmethod
    def history(
        service_key: str,
        *,
        session: Session,
        limit: int,
    ) -> list[ExecutionResult]:
        return [
            _result(record)
            for record in ExecutionRepository(session).history(
                service_key,
                limit=limit,
            )
        ]


def _result(record, checks: list[ExecutionCheck] | None = None) -> ExecutionResult:
    return ExecutionResult(
        id=record.id,
        recommendation_id=record.recommendation_id,
        service_key=record.service_key,
        policy_id=record.policy_id,
        previous_version=record.previous_version,
        resulting_version=record.resulting_version,
        previous_rate=float(record.previous_rate),
        proposed_rate=float(record.proposed_rate),
        status=record.status,
        failure_reason=record.failure_reason,
        started_at=record.started_at,
        completed_at=record.completed_at,
        checks=checks or [],
    )
