from datetime import datetime, timedelta, timezone

from app.config import Settings
from app.forecasting.metrics import RECOMMENDATION_GENERATION_SECONDS
from app.recommendations.recommendation_engine import RecommendationEngine
from app.recommendations.schemas import RecommendationEvaluationInput
from app.storage.repositories import RecommendationRepository


class RecommendationService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.engine = RecommendationEngine(settings)

    def generate(
        self,
        service_key: str,
        inputs: RecommendationEvaluationInput,
        repository: RecommendationRepository,
        *,
        now: datetime | None = None,
    ):
        generated_at = now or datetime.now(timezone.utc)
        with RECOMMENDATION_GENERATION_SECONDS.labels(service_key).time():
            return self._generate(
                service_key,
                inputs,
                repository,
                generated_at,
            )

    def _generate(
        self,
        service_key: str,
        inputs: RecommendationEvaluationInput,
        repository: RecommendationRepository,
        generated_at: datetime,
    ):
        previous = repository.latest_actionable(service_key)
        cooldown_active = (
            previous is not None
            and _as_utc(generated_at) - _as_utc(previous.generated_at)
            < timedelta(seconds=self.settings.cooldown_seconds)
        )
        action, rate, reason = self.engine.recommend(
            inputs,
            now=generated_at,
            cooldown_active=cooldown_active,
        )
        return repository.create(
            service_key=service_key,
            scope="GLOBAL",
            current_rate=inputs.current_rate,
            recommended_rate=rate,
            action=action.value,
            reason=reason,
            forecast_rps=inputs.forecast_rps,
            forecast_confidence=inputs.forecast_confidence,
            safe_capacity_rps=inputs.safe_capacity_rps,
            policy_version=inputs.policy_version,
            generated_at=generated_at,
            expires_at=generated_at + timedelta(
                seconds=self.settings.recommendation_ttl_seconds
            ),
        )


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
