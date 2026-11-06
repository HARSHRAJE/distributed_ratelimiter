from dataclasses import dataclass
from datetime import datetime, timezone

from app.recommendations.schemas import (
    RecommendationAction,
    RecommendationEvaluationInput,
)


@dataclass(frozen=True)
class Decision:
    action: RecommendationAction
    proposed_rate: float
    reason: str
    emergency: bool = False


def evaluate_decision(
    inputs: RecommendationEvaluationInput,
    *,
    now: datetime,
    maximum_telemetry_age_seconds: int,
    minimum_forecast_confidence: float,
    maximum_cpu_utilization: float,
    maximum_p95_latency_ms: float,
    maximum_p99_latency_ms: float,
    maximum_5xx_rate: float,
    maximum_queue_depth: float,
) -> Decision:
    telemetry_timestamp = _as_utc(inputs.telemetry_timestamp)
    current_time = _as_utc(now)
    age_seconds = (current_time - telemetry_timestamp).total_seconds()
    if age_seconds < 0 or age_seconds > maximum_telemetry_age_seconds:
        return _hold(inputs.current_rate, "Telemetry is stale or from the future")
    if inputs.forecast_confidence < minimum_forecast_confidence:
        return _hold(inputs.current_rate, "Forecast confidence is below the minimum")

    if inputs.error_rate > maximum_5xx_rate:
        return _decrease(inputs, "5xx rate exceeds the configured threshold")
    if inputs.cpu_utilization > maximum_cpu_utilization:
        return _decrease(inputs, "CPU utilization indicates backend overload")
    if (
        inputs.p95_latency_ms > maximum_p95_latency_ms
        or inputs.p99_latency_ms > maximum_p99_latency_ms
    ):
        return _decrease(inputs, "Backend latency exceeds the configured threshold")
    if inputs.queue_depth > maximum_queue_depth:
        return _decrease(inputs, "Queue depth indicates backend overload")

    if inputs.forecast_rps > inputs.safe_capacity_rps:
        if inputs.current_rate > inputs.safe_capacity_rps:
            return Decision(
                action=RecommendationAction.DECREASE,
                proposed_rate=inputs.safe_capacity_rps,
                reason="Forecast demand exceeds safe capacity and current rate",
            )
        return _hold(
            inputs.current_rate,
            "Forecast demand exceeds safe capacity; current rate is already safe",
        )
    if inputs.current_rate < min(inputs.safe_capacity_rps, inputs.max_refill_rate):
        return Decision(
            action=RecommendationAction.INCREASE,
            proposed_rate=min(inputs.safe_capacity_rps, inputs.max_refill_rate),
            reason="Backend is healthy and global rate is below safe capacity",
        )
    return _hold(inputs.current_rate, "No meaningful rate change is required")


def _hold(rate: float, reason: str) -> Decision:
    return Decision(RecommendationAction.HOLD, rate, reason)


def _decrease(inputs: RecommendationEvaluationInput, reason: str) -> Decision:
    target = min(
        inputs.current_rate * 0.9,
        inputs.safe_capacity_rps,
    )
    return Decision(
        action=RecommendationAction.DECREASE,
        proposed_rate=max(inputs.min_refill_rate, target),
        reason=reason,
        emergency=True,
    )


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
