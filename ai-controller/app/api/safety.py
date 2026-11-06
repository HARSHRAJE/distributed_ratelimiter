from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from app.api.telemetry import get_session, require_internal_api_key
from app.config import Settings
from app.recommendations.schemas import RecommendationRecordSchema
from app.safety.safety_validator import SafetyValidator
from app.safety.schemas import ValidationContext, ValidationHistory, ValidationResult
from app.safety.validation_result import VALIDATOR_VERSION
from app.storage.repositories import (
    RecommendationRepository,
    RecommendationValidationRepository,
)

router = APIRouter(
    prefix="/api/v1/safety",
    tags=["safety"],
    dependencies=[Depends(require_internal_api_key)],
)


@router.post(
    "/validate/{recommendation_id}",
    response_model=ValidationResult,
)
def validate_recommendation(
    recommendation_id: UUID,
    context: ValidationContext,
    request: Request,
    session: Session = Depends(get_session),
) -> ValidationResult:
    request_settings: Settings = request.app.state.settings
    recommendation_repository = RecommendationRepository(session)
    record = recommendation_repository.get(recommendation_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Recommendation not found")

    now = datetime.now(timezone.utc)
    cooldown_active = False
    if (
        record.action != "HOLD"
        and request_settings.cooldown_seconds > 0
    ):
        cooldown_active = recommendation_repository.has_recent_conflict(
            record.service_key,
            excluding_recommendation_id=record.id,
            since=now - timedelta(seconds=request_settings.cooldown_seconds),
            now=now,
        )

    result = SafetyValidator(request_settings).validate(
        RecommendationRecordSchema.model_validate(record),
        context,
        cooldown_active=cooldown_active,
        now=now,
    )
    RecommendationValidationRepository(session).create(
        validation_id=result.id,
        recommendation_id=result.recommendation_id,
        status=result.status.value,
        validation_result=result.model_dump(mode="json"),
        validated_at=result.validated_at,
        validator_version=VALIDATOR_VERSION,
    )
    return result


@router.get(
    "/{recommendation_id}/latest",
    response_model=ValidationResult,
)
def latest_validation(
    recommendation_id: UUID,
    session: Session = Depends(get_session),
) -> ValidationResult:
    record = RecommendationValidationRepository(session).latest(
        recommendation_id
    )
    if record is None:
        raise HTTPException(status_code=404, detail="Validation not found")
    return ValidationResult.model_validate(record.validation_result)


@router.get(
    "/{recommendation_id}/history",
    response_model=ValidationHistory,
)
def validation_history(
    recommendation_id: UUID,
    limit: int = Query(default=100, ge=1, le=1000),
    session: Session = Depends(get_session),
) -> ValidationHistory:
    records = RecommendationValidationRepository(session).history(
        recommendation_id,
        limit=limit,
    )
    return ValidationHistory(
        recommendation_id=recommendation_id,
        validations=[
            ValidationResult.model_validate(record.validation_result)
            for record in records
        ],
    )
