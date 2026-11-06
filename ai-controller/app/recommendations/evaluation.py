from dataclasses import dataclass
import math
from typing import Sequence


@dataclass(frozen=True)
class RecommendationQuality:
    sample_count: int
    forecast_mae_rps: float | None
    capacity_breach_count: int


def evaluate_historical_quality(
    forecasts_and_actuals: Sequence[tuple[float, float, float]],
) -> RecommendationQuality:
    """Evaluate demand forecasts against actual RPS and measured safe capacity."""
    if not forecasts_and_actuals:
        return RecommendationQuality(0, None, 0)
    errors: list[float] = []
    capacity_breaches = 0
    for forecast_rps, actual_rps, safe_capacity_rps in forecasts_and_actuals:
        values = (forecast_rps, actual_rps, safe_capacity_rps)
        if any(not math.isfinite(value) or value < 0 for value in values):
            raise ValueError("Evaluation values must be finite and non-negative")
        errors.append(abs(forecast_rps - actual_rps))
        if actual_rps > safe_capacity_rps:
            capacity_breaches += 1
    return RecommendationQuality(
        sample_count=len(errors),
        forecast_mae_rps=sum(errors) / len(errors),
        capacity_breach_count=capacity_breaches,
    )
