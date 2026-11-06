from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from app.api.telemetry import get_session, require_internal_api_key
from app.recommendations.recommendation_service import RecommendationService
from app.recommendations.schemas import (
    RecommendationApproval,
    RecommendationEvaluationInput,
    RecommendationHistory,
    RecommendationRecordSchema,
    RecommendationStatus,
)
from app.storage.repositories import RecommendationRepository

router = APIRouter(
    prefix="/api/v1/recommendations",
    tags=["recommendations"],
    dependencies=[Depends(require_internal_api_key)],
)


def _check_service_key(request: Request, service_key: str) -> None:
    if service_key not in request.app.state.settings.service_keys:
        raise HTTPException(status_code=404, detail="Service not found")


@router.post(
    "/evaluate/{serviceKey}",
    response_model=RecommendationRecordSchema,
)
def evaluate_recommendation(
    serviceKey: str,
    payload: RecommendationEvaluationInput,
    request: Request,
    session: Session = Depends(get_session),
) -> RecommendationRecordSchema:
    _check_service_key(request, serviceKey)
    record = RecommendationService(request.app.state.settings).generate(
        serviceKey,
        payload,
        RecommendationRepository(session),
    )
    return RecommendationRecordSchema.model_validate(record)


@router.get(
    "/{service_key}/latest",
    response_model=RecommendationRecordSchema,
)
def latest_recommendation(
    service_key: str,
    request: Request,
    session: Session = Depends(get_session),
) -> RecommendationRecordSchema:
    _check_service_key(request, service_key)
    record = RecommendationRepository(session).latest(service_key)
    if record is None:
        raise HTTPException(status_code=404, detail="Recommendation not found")
    return RecommendationRecordSchema.model_validate(record)


@router.get("/{service_key}/history", response_model=RecommendationHistory)
def recommendation_history(
    service_key: str,
    request: Request,
    limit: int = Query(default=100, ge=1, le=1000),
    session: Session = Depends(get_session),
) -> RecommendationHistory:
    _check_service_key(request, service_key)
    records = RecommendationRepository(session).history(
        service_key,
        limit=limit,
    )
    return RecommendationHistory(
        service_key=service_key,
        recommendations=[
            RecommendationRecordSchema.model_validate(record)
            for record in records
        ],
    )


@router.patch(
    "/{recommendation_id}/accept",
    response_model=RecommendationRecordSchema,
)
def accept_recommendation(
    recommendation_id: UUID,
    payload: RecommendationApproval,
    session: Session = Depends(get_session),
) -> RecommendationRecordSchema:
    repository = RecommendationRepository(session)
    record = _pending_record(repository, recommendation_id)
    if payload.current_policy_version != record.policy_version:
        raise HTTPException(
            status_code=409,
            detail="Recommendation is based on an outdated policy version",
        )
    updated = repository.update_status(record, RecommendationStatus.ACCEPTED.value)
    return RecommendationRecordSchema.model_validate(updated)


@router.patch(
    "/{recommendation_id}/reject",
    response_model=RecommendationRecordSchema,
)
def reject_recommendation(
    recommendation_id: UUID,
    session: Session = Depends(get_session),
) -> RecommendationRecordSchema:
    repository = RecommendationRepository(session)
    record = _pending_record(repository, recommendation_id)
    updated = repository.update_status(record, RecommendationStatus.REJECTED.value)
    return RecommendationRecordSchema.model_validate(updated)


def _pending_record(
    repository: RecommendationRepository,
    recommendation_id: UUID,
):
    record = repository.get(recommendation_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Recommendation not found")
    if record.status != RecommendationStatus.PENDING.value:
        raise HTTPException(
            status_code=409,
            detail=f"Recommendation is {record.status.lower()}",
        )
    if _as_utc(record.expires_at) <= datetime.now(timezone.utc):
        repository.update_status(record, RecommendationStatus.EXPIRED.value)
        raise HTTPException(status_code=409, detail="Recommendation has expired")
    return record


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
