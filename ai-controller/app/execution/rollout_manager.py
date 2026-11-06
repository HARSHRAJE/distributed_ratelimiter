from datetime import datetime, timezone
from math import isclose

from app.config import Settings
from app.execution.execution_repository import ExecutionRepository
from app.execution.policy_client import PolicyClient
from app.execution.schemas import ServiceControlResult
from app.telemetry.models import ExecutionServiceControlRecord


class RolloutError(RuntimeError):
    pass


class RolloutManager:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def enable(
        self,
        service_key: str,
        *,
        repository: ExecutionRepository,
        client: PolicyClient,
        now: datetime | None = None,
    ) -> ServiceControlResult:
        self._check_service(service_key)
        if (
            not self.settings.execution_enabled
            or self.emergency_active(repository)
        ):
            raise RolloutError("Execution is disabled or emergency kill switch is active")
        for existing in self.settings.execution_enabled_services:
            control = repository.control(existing)
            if (
                existing != service_key
                and control is not None
                and control.enabled
            ):
                raise RolloutError(
                    "Only one service can be enabled during the initial rollout"
                )
        current_time = now or datetime.now(timezone.utc)
        control = repository.control(service_key)
        row = control or ExecutionServiceControlRecord(
            service_key=service_key,
            enabled=False,
            manual_override=False,
            rollout_started_at=None,
            paused_reason=None,
            updated_at=current_time,
        )
        row.enabled = False
        row.paused_reason = "Awaiting effective policy synchronization"
        row.updated_at = current_time
        repository.save_control(row)

        policy = client.get_service(service_key)
        updated_policy = client.set_adaptive_control(
            service_key,
            expected_version=policy.config_version,
            enabled=True,
        )
        effective = client.get_effective(service_key)
        if (
            effective.config_version != updated_policy.config_version
            or not isclose(
                effective.global_refill_rate,
                updated_policy.global_refill_rate,
                rel_tol=0,
                abs_tol=0.001,
            )
        ):
            row.paused_reason = (
                "Effective policy has not synchronized; execution remains disabled"
            )
            row.updated_at = current_time
            repository.save_control(row)
            raise RolloutError(row.paused_reason)

        row.enabled = True
        row.manual_override = False
        if control is None or control.rollout_started_at is None:
            row.rollout_started_at = current_time
        row.paused_reason = None
        row.updated_at = current_time
        repository.save_control(row)
        return ServiceControlResult(
            service_key=service_key,
            enabled=True,
            manual_override=False,
            rollout_started_at=row.rollout_started_at,
            paused_reason=None,
        )

    def disable(
        self,
        service_key: str,
        *,
        manual_override: bool,
        repository: ExecutionRepository,
        client: PolicyClient,
        now: datetime | None = None,
    ) -> ServiceControlResult:
        current_time = now or datetime.now(timezone.utc)
        control = repository.control(service_key)
        row = control or ExecutionServiceControlRecord(
            service_key=service_key,
            enabled=False,
            manual_override=False,
            rollout_started_at=None,
            paused_reason=None,
            updated_at=current_time,
        )
        row.enabled = False
        row.manual_override = manual_override
        row.paused_reason = (
            "Manual override is active" if manual_override else None
        )
        row.updated_at = current_time
        repository.save_control(row)

        policy = client.get_service(service_key)
        updated_policy = client.set_adaptive_control(
            service_key,
            expected_version=policy.config_version,
            enabled=False,
        )
        effective = client.get_effective(service_key)
        if (
            effective.config_version != updated_policy.config_version
            or not isclose(
                effective.global_refill_rate,
                updated_policy.global_refill_rate,
                rel_tol=0,
                abs_tol=0.001,
            )
        ):
            row.paused_reason = (
                "Execution is disabled locally; effective policy synchronization is pending"
            )
            row.updated_at = current_time
            repository.save_control(row)
            raise RolloutError(row.paused_reason)

        return ServiceControlResult(
            service_key=service_key,
            enabled=False,
            manual_override=manual_override,
            rollout_started_at=row.rollout_started_at,
            paused_reason=row.paused_reason,
        )

    def pause(
        self,
        service_key: str,
        reason: str,
        *,
        repository: ExecutionRepository,
        now: datetime | None = None,
    ) -> None:
        repository.pause_service(
            service_key,
            reason=reason,
            now=now or datetime.now(timezone.utc),
        )

    def set_global_kill_switch(
        self,
        *,
        active: bool,
        repository: ExecutionRepository,
        client: PolicyClient,
        now: datetime | None = None,
    ) -> bool:
        if not active and self.settings.emergency_kill_switch:
            raise RolloutError(
                "The deployment-level emergency kill switch is still active"
            )
        current_time = now or datetime.now(timezone.utc)
        if active:
            repository.set_global_kill_switch(
                active=True,
                now=current_time,
            )
            client.set_global_kill_switch(active=True)
        else:
            client.set_global_kill_switch(active=False)
            repository.set_global_kill_switch(
                active=False,
                now=current_time,
            )
        return active

    def emergency_active(self, repository: ExecutionRepository) -> bool:
        return (
            self.settings.emergency_kill_switch
            or repository.global_kill_switch_active()
        )

    def _check_service(self, service_key: str) -> None:
        if service_key not in self.settings.execution_enabled_services:
            raise RolloutError(
                "Service is not in the initial rollout allowlist"
            )
