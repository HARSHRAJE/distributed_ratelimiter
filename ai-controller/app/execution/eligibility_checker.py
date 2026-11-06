from datetime import datetime, timedelta, timezone
from math import isclose

from app.config import Settings
from app.execution.execution_repository import ExecutionRepository
from app.execution.policy_client import ServicePolicy
from app.execution.schemas import ExecutionCheck
from app.telemetry.models import (
    ExecutionServiceControlRecord,
    PolicyRecommendationRecord,
    RecommendationValidationRecord,
    ShadowEvaluationRecord,
    TelemetrySampleRecord,
)


class EligibilityChecker:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def check(
        self,
        *,
        recommendation: PolicyRecommendationRecord,
        validation: RecommendationValidationRecord | None,
        shadow: ShadowEvaluationRecord | None,
        telemetry: TelemetrySampleRecord | None,
        control: ExecutionServiceControlRecord | None,
        service: ServicePolicy,
        repository: ExecutionRepository,
        global_kill_switch_active: bool = False,
        now: datetime | None = None,
    ) -> list[ExecutionCheck]:
        current_time = _utc(now or datetime.now(timezone.utc))
        checks: list[ExecutionCheck] = []
        self._check(
            checks,
            "GLOBAL_EXECUTION_ENABLED",
            self.settings.execution_enabled
            and not self.settings.emergency_kill_switch,
            "Execution is enabled and emergency kill switch is clear"
            if self.settings.execution_enabled
            and not self.settings.emergency_kill_switch
            else "Execution is disabled or emergency kill switch is active",
        )
        self._check(
            checks,
            "DYNAMIC_EMERGENCY_KILL_SWITCH",
            not global_kill_switch_active,
            "Global emergency kill switch is inactive"
            if not global_kill_switch_active
            else "Global emergency kill switch is active",
        )
        self._check(
            checks,
            "ROLLOUT_ALLOWLIST",
            recommendation.service_key
            in self.settings.execution_enabled_services
            and len(self.settings.execution_enabled_services) <= 1,
            "Service is in the single-service rollout allowlist"
            if recommendation.service_key
            in self.settings.execution_enabled_services
            else "Service is not enabled for the initial rollout",
        )
        self._check(
            checks,
            "SERVICE_CONTROL",
            control is not None
            and control.enabled
            and not control.manual_override
            and control.paused_reason is None,
            "Per-service adaptive execution is enabled without an override"
            if control is not None
            and control.enabled
            and not control.manual_override
            and control.paused_reason is None
            else "Service execution is disabled, overridden, or paused",
        )
        rollout_active = (
            control is not None
            and control.rollout_started_at is not None
            and current_time
            <= _utc(control.rollout_started_at)
            + timedelta(hours=self.settings.execution_rollout_duration_hours)
        )
        self._check(
            checks,
            "ROLLOUT_WINDOW",
            rollout_active,
            "Service is within the configured rollout duration"
            if rollout_active
            else "Service rollout has not started or has expired",
        )
        self._check(
            checks,
            "RECOMMENDATION_APPROVAL",
            recommendation.status == "ACCEPTED",
            "Recommendation has explicit approval"
            if recommendation.status == "ACCEPTED"
            else "Recommendation must be accepted before execution",
        )
        self._check(
            checks,
            "GLOBAL_SCOPE",
            recommendation.scope == "GLOBAL",
            "Recommendation targets the global service policy"
            if recommendation.scope == "GLOBAL"
            else "Only global service recommendations can be executed",
        )
        self._check(
            checks,
            "ACTIONABLE_RECOMMENDATION",
            recommendation.action in ("INCREASE", "DECREASE"),
            "Recommendation requests a rate change"
            if recommendation.action in ("INCREASE", "DECREASE")
            else "HOLD recommendations cannot be executed",
        )
        self._check(
            checks,
            "RECOMMENDATION_EXPIRATION",
            _utc(recommendation.expires_at) > current_time,
            "Recommendation has not expired"
            if _utc(recommendation.expires_at) > current_time
            else "Recommendation has expired",
        )
        self._check(
            checks,
            "SAFETY_VALIDATION",
            validation is not None and validation.status == "VALID",
            "Latest safety validation passed"
            if validation is not None and validation.status == "VALID"
            else "Recommendation has no passing safety validation",
        )
        self._check(
            checks,
            "ADAPTIVE_CONTROL",
            service.adaptive_enabled,
            "Policy Service adaptive control is enabled"
            if service.adaptive_enabled
            else "Policy Service adaptive control is disabled",
        )
        self._check(
            checks,
            "POLICY_VERSION",
            recommendation.policy_version == service.config_version,
            "Recommendation matches the current policy version"
            if recommendation.policy_version == service.config_version
            else "Recommendation uses an outdated policy version",
        )
        current_rate = service.global_refill_rate
        proposed_rate = float(recommendation.recommended_rate)
        self._check(
            checks,
            "CURRENT_RATE",
            isclose(
                float(recommendation.current_rate),
                current_rate,
                rel_tol=0,
                abs_tol=0.001,
            ),
            "Recommendation current rate matches Policy Service"
            if isclose(
                float(recommendation.current_rate),
                current_rate,
                rel_tol=0,
                abs_tol=0.001,
            )
            else "Recommendation is based on a different current rate",
        )
        self._check(
            checks,
            "RATE_BOUNDS",
            self.settings.execution_minimum_rate_rps
            <= proposed_rate
            <= min(
                service.hard_max_refill_rate,
                float(recommendation.safe_capacity_rps),
            ),
            "Proposed rate is within minimum, hard maximum, and safe capacity"
            if self.settings.execution_minimum_rate_rps
            <= proposed_rate
            <= min(
                service.hard_max_refill_rate,
                float(recommendation.safe_capacity_rps),
            )
            else "Proposed rate violates a configured rate or capacity bound",
        )
        maximum_delta = current_rate * (
            self.settings.execution_max_change_percent / 100
        )
        self._check(
            checks,
            "MAXIMUM_CHANGE",
            abs(proposed_rate - current_rate) <= maximum_delta + 0.001,
            f"Change is within {self.settings.execution_max_change_percent:g}%",
            f"Change exceeds {self.settings.execution_max_change_percent:g}%",
        )

        telemetry_age = (
            (current_time - _utc(telemetry.window_start)).total_seconds()
            if telemetry is not None
            else None
        )
        fresh_telemetry = (
            telemetry is not None
            and telemetry.data_quality == "valid"
            and telemetry_age is not None
            and 0 <= telemetry_age
            <= self.settings.maximum_telemetry_age_seconds
        )
        self._check(
            checks,
            "TELEMETRY_FRESHNESS",
            fresh_telemetry,
            "Telemetry is recent and valid"
            if fresh_telemetry
            else "Telemetry is missing, invalid, stale, or from the future",
        )
        self._check(
            checks,
            "FORECAST_CONFIDENCE",
            recommendation.forecast_confidence
            >= self.settings.minimum_forecast_confidence,
            "Forecast confidence meets the configured threshold"
            if recommendation.forecast_confidence
            >= self.settings.minimum_forecast_confidence
            else "Forecast confidence is below the configured threshold",
        )

        cooldown_since = current_time - timedelta(
            seconds=self.settings.execution_cooldown_seconds
        )
        last_change = repository.last_change_at(recommendation.service_key)
        cooldown_elapsed = (
            last_change is None or _utc(last_change) <= cooldown_since
        )
        self._check(
            checks,
            "COOLDOWN",
            cooldown_elapsed,
            "Minimum cooldown has elapsed"
            if cooldown_elapsed
            else "A previous rate change is still within cooldown",
        )
        changes_this_hour = repository.recent_changes(
            recommendation.service_key,
            since=current_time - timedelta(hours=1),
        )
        self._check(
            checks,
            "HOURLY_CHANGE_LIMIT",
            changes_this_hour < self.settings.execution_max_changes_per_hour,
            "Hourly change limit has not been reached"
            if changes_this_hour < self.settings.execution_max_changes_per_hour
            else "Maximum policy changes per hour has been reached",
        )
        active = repository.active_for_service(recommendation.service_key)
        self._check(
            checks,
            "NO_PENDING_EXECUTION",
            active is None,
            "No policy execution is pending"
            if active is None
            else "Another policy execution is still pending",
        )

        latest_execution = repository.latest(recommendation.service_key)
        rollback_active = (
            latest_execution is not None
            and latest_execution.status == "ROLLBACK_PENDING"
        )
        self._check(
            checks,
            "NO_ROLLBACK",
            not rollback_active,
            "Service is not in rollback mode"
            if not rollback_active
            else "Service is in rollback mode",
        )
        self._check_shadow(
            checks,
            recommendation=recommendation,
            shadow=shadow,
            service=service,
            now=current_time,
        )
        return checks

    def _check_shadow(
        self,
        checks: list[ExecutionCheck],
        *,
        recommendation: PolicyRecommendationRecord,
        shadow: ShadowEvaluationRecord | None,
        service: ServicePolicy,
        now: datetime,
    ) -> None:
        valid_record = (
            shadow is not None
            and shadow.recommendation_id == recommendation.id
            and shadow.current_policy_version == service.config_version
            and _utc(shadow.created_at)
            >= now
            - timedelta(
                seconds=self.settings.execution_maximum_shadow_age_seconds
            )
        )
        if not valid_record:
            self._check(
                checks,
                "SHADOW_EVALUATION",
                False,
                "A current shadow evaluation for this recommendation is required",
            )
            return
        assert shadow is not None
        strategies = shadow.evaluation_result.get("strategies", [])
        outcome = next(
            (
                item
                for item in strategies
                if item.get("strategy") == "FORECAST_ASSISTED"
            ),
            None,
        )
        if outcome is None:
            self._check(
                checks,
                "SHADOW_ACCEPTANCE",
                False,
                "Shadow evaluation has no forecast-assisted outcome",
            )
            return
        proposed_matches = isclose(
            float(outcome.get("applied_global_rate_rps", -1)),
            float(recommendation.recommended_rate),
            rel_tol=0,
            abs_tol=0.001,
        )
        admitted = float(outcome.get("estimated_admitted_rps", float("inf")))
        capacity_respected = admitted <= float(recommendation.safe_capacity_rps)
        forecast_error = outcome.get("forecast_error_rps")
        forecast_error_limit = max(
            1.0,
            float(recommendation.forecast_rps)
            * self.settings.execution_maximum_shadow_forecast_error_percent
            / 100,
        )
        forecast_reliable = (
            forecast_error is not None
            and float(forecast_error) <= forecast_error_limit
        )
        passed = proposed_matches and capacity_respected and forecast_reliable
        self._check(
            checks,
            "SHADOW_ACCEPTANCE",
            passed,
            "Shadow outcome matches the proposal, respects capacity, and "
            "meets the forecast error threshold"
            if passed
            else "Shadow outcome failed proposal, capacity, or forecast-error criteria",
        )

    @staticmethod
    def _check(
        checks: list[ExecutionCheck],
        name: str,
        passed: bool,
        passed_message: str,
        failed_message: str | None = None,
    ) -> None:
        checks.append(
            ExecutionCheck(
                check=name,
                passed=passed,
                message=passed_message if passed else (
                    failed_message or passed_message
                ),
            )
        )


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
