from datetime import datetime, timezone
from math import isclose

from app.execution.execution_repository import ExecutionRepository
from app.execution.policy_client import (
    AcceptedExecution,
    PolicyClient,
    PolicyClientError,
    ServicePolicy,
)
from app.execution.rollout_manager import RolloutManager
from app.telemetry.models import PolicyExecutionRecord
from app.circuit_breaker.repository import BreakerRepository
from app.config import Settings


class ExecutionCoordinator:
    def __init__(
        self,
        client: PolicyClient,
        repository: ExecutionRepository,
        rollout_manager: RolloutManager,
        gateway_policy_cache_ttl_seconds: float,
        settings: Settings | None = None,
    ) -> None:
        self.client = client
        self.repository = repository
        self.rollout_manager = rollout_manager
        self.gateway_policy_cache_ttl_seconds = (
            gateway_policy_cache_ttl_seconds
        )
        self.settings = settings

    def submit_or_resume(
        self,
        record: PolicyExecutionRecord,
        service: ServicePolicy,
    ) -> PolicyExecutionRecord:
        acceptance = self.client.execution_status(service.id, record.id)
        policy_submitted_at = None
        if not acceptance.accepted and record.status == "SUBMITTED":
            return record
        if not acceptance.accepted:
            if self.rollout_manager.emergency_active(self.repository):
                return self.repository.update(
                    record,
                    status="FAILED",
                    failure_reason=(
                        "Global emergency kill switch activated before submit"
                    ),
                    completed_at=datetime.now(timezone.utc),
                )
            latest = self.client.get_service(record.service_key)
            if (
                latest.config_version != record.previous_version
                or not isclose(
                    latest.global_refill_rate,
                    float(record.previous_rate),
                    rel_tol=0,
                    abs_tol=0.001,
                )
            ):
                return self.repository.update(
                    record,
                    status="FAILED",
                    failure_reason=(
                        "Policy changed before submission; expected version "
                        f"{record.previous_version}, found {latest.config_version}"
                    ),
                    completed_at=datetime.now(timezone.utc),
                )
            try:
                updated = self.client.submit(
                    latest,
                    execution_id=record.id,
                    expected_version=record.previous_version,
                    proposed_rate=float(record.proposed_rate),
                )
                acceptance = AcceptedExecution(
                    True,
                    updated.config_version,
                    updated.global_refill_rate,
                )
                policy_submitted_at = datetime.now(timezone.utc)
            except PolicyClientError as error:
                self._report_component(
                    record.service_key,
                    "POLICY_SERVICE",
                    healthy=False,
                    reason=str(error),
                    failure_threshold=(
                        self.settings.breaker_policy_failure_threshold
                        if self.settings is not None
                        else 1
                    ),
                )
                if not error.ambiguous:
                    return self.repository.update(
                        record,
                        status="FAILED",
                        failure_reason=str(error),
                        completed_at=datetime.now(timezone.utc),
                    )
                try:
                    acceptance = self.client.execution_status(
                        service.id,
                        record.id,
                    )
                except PolicyClientError as status_error:
                    self._report_component(
                        record.service_key,
                        "POLICY_SERVICE",
                        healthy=False,
                        reason=str(status_error),
                        failure_threshold=(
                            self.settings.breaker_policy_failure_threshold
                            if self.settings is not None
                            else 1
                        ),
                    )
                    acceptance = AcceptedExecution(False, None, None)
                if not acceptance.accepted:
                    self.rollout_manager.pause(
                        record.service_key,
                        "Policy update outcome is ambiguous; execution paused",
                        repository=self.repository,
                    )
                    return self.repository.update(
                        record,
                        status="SUBMITTED",
                        failure_reason=(
                            "Policy Service timed out; idempotency status did "
                            "not confirm completion. No second update was sent."
                        ),
                    )
        if not acceptance.accepted or acceptance.resulting_version is None:
            return self.repository.update(
                record,
                status="SUBMITTED",
                failure_reason="Policy Service has not confirmed submission",
            )
        if not isclose(
            float(acceptance.resulting_rate or -1),
            float(record.proposed_rate),
            rel_tol=0,
            abs_tol=0.001,
        ):
            return self.repository.update(
                record,
                status="FAILED",
                resulting_version=acceptance.resulting_version,
                failure_reason="Policy Service accepted a different rate",
                completed_at=datetime.now(timezone.utc),
            )
        return self.repository.update(
            record,
            status="SUBMITTED",
            resulting_version=acceptance.resulting_version,
            policy_submitted_at=policy_submitted_at,
            failure_reason=None,
        )

    def verify_effective(
        self,
        record: PolicyExecutionRecord,
    ) -> PolicyExecutionRecord:
        if record.status != "SUBMITTED":
            return record
        resulting_version = record.resulting_version
        if resulting_version is None:
            try:
                service = self.client.get_service(record.service_key)
                accepted = self.client.execution_status(service.id, record.id)
            except PolicyClientError as error:
                self._report_component(
                    record.service_key,
                    "POLICY_SERVICE",
                    healthy=False,
                    reason=str(error),
                    failure_threshold=(
                        self.settings.breaker_policy_failure_threshold
                        if self.settings is not None
                        else 1
                    ),
                )
                return self._pause_pending(record, str(error))
            if not accepted.accepted or accepted.resulting_version is None:
                return self._pause_pending(
                    record,
                    "Policy Service has not confirmed the ambiguous update",
                )
            if not isclose(
                float(accepted.resulting_rate or -1),
                float(record.proposed_rate),
                rel_tol=0,
                abs_tol=0.001,
            ):
                return self.repository.update(
                    record,
                    status="FAILED",
                    resulting_version=accepted.resulting_version,
                    failure_reason="Policy Service recorded a different rate",
                    completed_at=datetime.now(timezone.utc),
                )
            record = self.repository.update(
                record,
                status="SUBMITTED",
                resulting_version=accepted.resulting_version,
                failure_reason=None,
            )
            resulting_version = accepted.resulting_version
        try:
            effective = self.client.get_effective(record.service_key)
        except PolicyClientError as error:
            self._report_component(
                record.service_key,
                "POLICY_SERVICE",
                healthy=False,
                reason=str(error),
                failure_threshold=(
                    self.settings.breaker_policy_failure_threshold
                    if self.settings is not None
                    else 1
                ),
            )
            return self._pause_pending(record, str(error))
        if effective.config_version < resulting_version:
            self._report_component(
                record.service_key,
                "REDIS_SYNC",
                healthy=False,
                reason="Redis has not synchronized the submitted policy version",
                failure_threshold=(
                    self.settings.breaker_redis_failure_threshold
                    if self.settings is not None
                    else 1
                ),
            )
            return self._pause_pending(
                record,
                "Redis has not synchronized the submitted policy version",
            )
        if effective.config_version > resulting_version:
            self._report_component(
                record.service_key,
                "REDIS_SYNC",
                healthy=False,
                reason="Effective Redis version is newer than the submitted version",
                failure_threshold=(
                    self.settings.breaker_redis_failure_threshold
                    if self.settings is not None
                    else 1
                ),
            )
            self.rollout_manager.pause(
                record.service_key,
                "Effective policy advanced beyond this execution version",
                repository=self.repository,
            )
            return self.repository.update(
                record,
                status="FAILED",
                failure_reason=(
                    "Effective Redis version is newer than the submitted version"
                ),
                completed_at=datetime.now(timezone.utc),
            )
        if not isclose(
            effective.global_refill_rate,
            float(record.proposed_rate),
            rel_tol=0,
            abs_tol=0.001,
        ):
            self._report_component(
                record.service_key,
                "REDIS_SYNC",
                healthy=False,
                reason="Effective Redis rate differs from proposal",
                failure_threshold=(
                    self.settings.breaker_redis_failure_threshold
                    if self.settings is not None
                    else 1
                ),
            )
            self.rollout_manager.pause(
                record.service_key,
                "Effective Redis rate does not match the submitted rate",
                repository=self.repository,
            )
            return self.repository.update(
                record,
                status="FAILED",
                failure_reason="Effective Redis rate differs from proposal",
                completed_at=datetime.now(timezone.utc),
            )
        self._report_component(
            record.service_key,
            "REDIS_SYNC",
            healthy=True,
            reason="Effective policy synchronized",
            failure_threshold=(
                self.settings.breaker_redis_failure_threshold
                if self.settings is not None
                else 1
            ),
        )
        now = datetime.now(timezone.utc)
        if record.effective_config_verified_at is None:
            record = self.repository.update(
                record,
                status="SUBMITTED",
                effective_config_verified_at=now,
                failure_reason="Waiting for gateway policy caches to expire",
            )
        if (
            now - _utc(record.effective_config_verified_at)
        ).total_seconds() < self.gateway_policy_cache_ttl_seconds:
            return self.repository.update(
                record,
                status="SUBMITTED",
                failure_reason="Waiting for gateway policy caches to expire",
            )
        return self.repository.update(
            record,
            status="APPLIED",
            resulting_version=resulting_version,
            failure_reason=None,
            completed_at=datetime.now(timezone.utc),
        )

    def _pause_pending(
        self,
        record: PolicyExecutionRecord,
        reason: str,
    ) -> PolicyExecutionRecord:
        self.rollout_manager.pause(
            record.service_key,
            reason,
            repository=self.repository,
        )
        return self.repository.update(
            record,
            status="SUBMITTED",
            failure_reason=reason,
        )

    def _report_component(
        self,
        service_key: str,
        component: str,
        *,
        healthy: bool,
        reason: str,
        failure_threshold: int,
    ) -> None:
        if self.settings is None:
            return
        BreakerRepository(self.repository.session, self.settings).report_component(
            service_key,
            component,
            healthy=healthy,
            reason=reason,
            failure_threshold=failure_threshold,
            now=datetime.now(timezone.utc),
        )


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
