from datetime import datetime

from app.config import Settings
from app.recommendations.decision_rules import evaluate_decision
from app.recommendations.safety_constraints import constrain_rate
from app.recommendations.schemas import (
    RecommendationAction,
    RecommendationEvaluationInput,
)


class RecommendationEngine:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def recommend(
        self,
        inputs: RecommendationEvaluationInput,
        *,
        now: datetime,
        cooldown_active: bool,
    ) -> tuple[RecommendationAction, float, str]:
        decision = evaluate_decision(
            inputs,
            now=now,
            maximum_telemetry_age_seconds=(
                self.settings.maximum_telemetry_age_seconds
            ),
            minimum_forecast_confidence=(
                self.settings.minimum_forecast_confidence
            ),
            maximum_cpu_utilization=self.settings.maximum_cpu_utilization,
            maximum_p95_latency_ms=self.settings.maximum_p95_latency_ms,
            maximum_p99_latency_ms=self.settings.maximum_p99_latency_ms,
            maximum_5xx_rate=self.settings.maximum_5xx_rate,
            maximum_queue_depth=self.settings.maximum_queue_depth,
        )
        if (
            cooldown_active
            and not decision.emergency
            and decision.action != RecommendationAction.HOLD
        ):
            decision = type(decision)(
                RecommendationAction.HOLD,
                inputs.current_rate,
                "Cooldown is active after a recent recommendation",
            )
        constrained = constrain_rate(
            current_rate=inputs.current_rate,
            proposed_rate=decision.proposed_rate,
            min_refill_rate=inputs.min_refill_rate,
            max_refill_rate=inputs.max_refill_rate,
            hard_max_refill_rate=inputs.hard_max_refill_rate,
            max_change_percent=self.settings.max_change_percent,
        )
        if constrained.action == RecommendationAction.HOLD:
            return (
                RecommendationAction.HOLD,
                constrained.rate,
                decision.reason,
            )
        return constrained.action, constrained.rate, decision.reason
