from collections.abc import Sequence

from app.shadow.schemas import StrategyName, StrategyOutcome, TrafficPoint
from app.shadow.traffic_simulator import SimulationResult


def calculate_outcome(
    *,
    strategy: StrategyName,
    applied_rate: float,
    simulation: SimulationResult,
    points: Sequence[TrafficPoint],
    forecast_rps: float,
) -> StrategyOutcome:
    duration = sum(point.window_seconds for point in points)
    actual_incoming = _weighted_mean(
        [(point.incoming_rps, point.window_seconds) for point in points]
    )
    actual_admitted = _weighted_optional_mean(
        [(point.allowed_rps, point.window_seconds) for point in points]
    )
    actual_rejected = _weighted_optional_mean(
        [(point.rejected_rps, point.window_seconds) for point in points]
    )
    return StrategyOutcome(
        strategy=strategy,
        applied_global_rate_rps=applied_rate,
        estimated_admitted_rps=simulation.admitted_requests / duration,
        estimated_rejected_rps=simulation.rejected_requests / duration,
        actual_admitted_rps=actual_admitted,
        actual_rejected_rps=actual_rejected,
        observed_p95_latency_ms=_weighted_optional_mean(
            [(point.p95_latency_ms, point.window_seconds) for point in points]
        ),
        observed_p99_latency_ms=_weighted_optional_mean(
            [(point.p99_latency_ms, point.window_seconds) for point in points]
        ),
        observed_error_rate=_weighted_optional_mean(
            [(point.error_rate, point.window_seconds) for point in points]
        ),
        observed_cpu_utilization=_weighted_optional_mean(
            [(point.cpu_utilization, point.window_seconds) for point in points]
        ),
        forecast_error_rps=abs(forecast_rps - actual_incoming),
    )


def _weighted_mean(values: list[tuple[float, int]]) -> float:
    duration = sum(weight for _, weight in values)
    return sum(value * weight for value, weight in values) / duration


def _weighted_optional_mean(
    values: list[tuple[float | None, int]],
) -> float | None:
    present = [(value, weight) for value, weight in values if value is not None]
    duration = sum(weight for _, weight in present)
    if not duration:
        return None
    return sum(value * weight for value, weight in present) / duration
