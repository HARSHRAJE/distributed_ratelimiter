from datetime import datetime, timezone

from app.recommendations.schemas import RecommendationRecordSchema
from app.safety.schemas import ValidationCheck, ValidationContext, ValidationRule


def evaluate_rules(
    recommendation: RecommendationRecordSchema,
    context: ValidationContext,
    *,
    now: datetime,
    max_change_percent: float,
    maximum_telemetry_age_seconds: int,
    minimum_forecast_confidence: float,
    cooldown_active: bool,
) -> list[ValidationCheck]:
    proposed = recommendation.recommended_rate
    current = context.current_rate
    lower_rate = max(
        context.min_refill_rate,
        current * (1 - max_change_percent / 100),
    )
    upper_rate = min(
        context.hard_max_refill_rate,
        current * (1 + max_change_percent / 100),
    )
    telemetry_time = _as_utc(context.telemetry_timestamp)
    current_time = _as_utc(now)
    telemetry_age = (current_time - telemetry_time).total_seconds()
    cooldown_passed = not cooldown_active or recommendation.action.value == "HOLD"

    return [
        _check(
            ValidationRule.HARD_MAX_RATE,
            proposed <= context.hard_max_refill_rate,
            "Rate is within service hard maximum"
            if proposed <= context.hard_max_refill_rate
            else "Proposed rate exceeds service hard maximum",
        ),
        _check(
            ValidationRule.MINIMUM_RATE,
            proposed >= context.min_refill_rate,
            "Rate is at or above configured minimum"
            if proposed >= context.min_refill_rate
            else "Proposed rate is below configured minimum",
        ),
        _check(
            ValidationRule.MAX_CHANGE_PERCENT,
            lower_rate <= proposed <= upper_rate,
            f"Proposed rate is within the {max_change_percent:g}% change range"
            if lower_rate <= proposed <= upper_rate
            else (
                f"Proposed change exceeds {max_change_percent:g}% "
                "or the permitted rate bounds"
            ),
        ),
        _check(
            ValidationRule.POLICY_VERSION,
            recommendation.policy_version == context.current_policy_version,
            "Recommendation matches current policy version"
            if recommendation.policy_version == context.current_policy_version
            else "Recommendation is based on an outdated policy version",
        ),
        _check(
            ValidationRule.EXPIRATION,
            _as_utc(recommendation.expires_at) > current_time,
            "Recommendation has not expired"
            if _as_utc(recommendation.expires_at) > current_time
            else "Recommendation has expired",
        ),
        _check(
            ValidationRule.TELEMETRY_FRESHNESS,
            0 <= telemetry_age <= maximum_telemetry_age_seconds,
            "Telemetry is recent"
            if 0 <= telemetry_age <= maximum_telemetry_age_seconds
            else "Telemetry is stale or from the future",
        ),
        _check(
            ValidationRule.FORECAST_CONFIDENCE,
            recommendation.forecast_confidence >= minimum_forecast_confidence,
            "Forecast confidence meets the configured threshold"
            if recommendation.forecast_confidence >= minimum_forecast_confidence
            else "Forecast confidence is below the configured threshold",
        ),
        _check(
            ValidationRule.COOLDOWN,
            cooldown_passed,
            "No conflicting change is active during cooldown"
            if cooldown_passed
            else "A conflicting recommendation is within the cooldown period",
        ),
        _check(
            ValidationRule.SERVICE_STATUS,
            context.adaptive_control_enabled,
            "Service is eligible for adaptive control"
            if context.adaptive_control_enabled
            else "Adaptive control is disabled for this service",
        ),
        _check(
            ValidationRule.SAFE_CAPACITY,
            proposed <= min(
                context.safe_capacity_rps,
                recommendation.safe_capacity_rps,
            ),
            "Rate respects measured safe service capacity"
            if proposed
            <= min(context.safe_capacity_rps, recommendation.safe_capacity_rps)
            else "Proposed rate exceeds safe service capacity",
        ),
        _check(
            ValidationRule.RECOMMENDATION_STATUS,
            recommendation.status.value == "PENDING",
            "Recommendation is still pending"
            if recommendation.status.value == "PENDING"
            else "Recommendation is no longer pending",
        ),
    ]


def _check(rule: ValidationRule, passed: bool, message: str) -> ValidationCheck:
    return ValidationCheck(rule=rule, passed=passed, message=message)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
