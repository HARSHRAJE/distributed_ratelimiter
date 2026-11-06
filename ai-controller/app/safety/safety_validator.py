from datetime import datetime, timezone
from uuid import uuid4

from app.config import Settings
from app.recommendations.schemas import RecommendationRecordSchema
from app.safety.schemas import ValidationContext, ValidationResult
from app.safety.validation_result import build_validation_result
from app.safety.validation_rules import evaluate_rules


class SafetyValidator:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def validate(
        self,
        recommendation: RecommendationRecordSchema,
        context: ValidationContext,
        *,
        cooldown_active: bool,
        now: datetime | None = None,
    ) -> ValidationResult:
        validated_at = now or datetime.now(timezone.utc)
        checks = evaluate_rules(
            recommendation,
            context,
            now=validated_at,
            max_change_percent=self.settings.max_change_percent,
            maximum_telemetry_age_seconds=(
                self.settings.maximum_telemetry_age_seconds
            ),
            minimum_forecast_confidence=(
                self.settings.minimum_forecast_confidence
            ),
            cooldown_active=cooldown_active,
        )
        return build_validation_result(
            validation_id=uuid4(),
            recommendation_id=recommendation.id,
            checks=checks,
            validated_at=validated_at,
        )
