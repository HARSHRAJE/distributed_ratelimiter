from dataclasses import dataclass

from app.recommendations.schemas import RecommendationAction


@dataclass(frozen=True)
class ConstrainedRate:
    rate: float
    action: RecommendationAction


def constrain_rate(
    *,
    current_rate: float,
    proposed_rate: float,
    min_refill_rate: float,
    max_refill_rate: float,
    hard_max_refill_rate: float,
    max_change_percent: float,
) -> ConstrainedRate:
    lower_bound = max(
        min_refill_rate,
        current_rate * (1 - max_change_percent / 100),
    )
    upper_bound = min(
        max_refill_rate,
        hard_max_refill_rate,
        current_rate * (1 + max_change_percent / 100),
    )
    rate = min(max(proposed_rate, lower_bound), upper_bound)
    if rate > current_rate:
        action = RecommendationAction.INCREASE
    elif rate < current_rate:
        action = RecommendationAction.DECREASE
    else:
        action = RecommendationAction.HOLD
    return ConstrainedRate(rate=rate, action=action)
