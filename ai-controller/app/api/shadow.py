from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from app.api.telemetry import get_session, require_internal_api_key
from app.shadow.schemas import (
    ShadowComparison,
    ShadowEvaluationRequest,
    ShadowEvaluationResult,
    ShadowHistory,
)
from app.shadow.shadow_repository import ShadowRepository
from app.shadow.shadow_service import ShadowEvaluationError, ShadowService
from app.telemetry.models import ShadowEvaluationRecord

router = APIRouter(
    prefix="/api/v1/shadow",
    tags=["shadow"],
    dependencies=[Depends(require_internal_api_key)],
)


def _check_service_key(request: Request, service_key: str) -> None:
    if service_key not in request.app.state.settings.service_keys:
        raise HTTPException(status_code=404, detail="Service not found")


@router.post(
    "/evaluate/{serviceKey}",
    response_model=ShadowEvaluationResult,
)
def evaluate_shadow(
    serviceKey: str,
    payload: ShadowEvaluationRequest,
    request: Request,
    session: Session = Depends(get_session),
) -> ShadowEvaluationResult:
    _check_service_key(request, serviceKey)
    try:
        return ShadowService(request.app.state.settings).evaluate(
            serviceKey,
            payload,
            ShadowRepository(session),
        )
    except ShadowEvaluationError as error:
        message = str(error).lower()
        status_code = 404 if "not found" in message else 409
        raise HTTPException(status_code=status_code, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.get("/{service_key}/latest", response_model=ShadowEvaluationResult)
def latest_shadow(
    service_key: str,
    request: Request,
    session: Session = Depends(get_session),
) -> ShadowEvaluationResult:
    _check_service_key(request, service_key)
    record = ShadowRepository(session).latest(service_key)
    if record is None:
        raise HTTPException(
            status_code=404,
            detail="Shadow evaluation not found",
        )
    return ShadowEvaluationResult.model_validate(
        _evaluation_values(record)
    )


@router.get("/{service_key}/history", response_model=ShadowHistory)
def shadow_history(
    service_key: str,
    request: Request,
    limit: int = Query(default=100, ge=1, le=1000),
    session: Session = Depends(get_session),
) -> ShadowHistory:
    _check_service_key(request, service_key)
    records = ShadowRepository(session).history(service_key, limit=limit)
    return ShadowHistory(
        service_key=service_key,
        evaluations=[
            ShadowEvaluationResult.model_validate(_evaluation_values(record))
            for record in records
        ],
    )


@router.get(
    "/{service_key}/comparison",
    response_model=ShadowComparison,
)
def compare_shadow_strategies(
    service_key: str,
    request: Request,
    limit: int = Query(default=100, ge=1, le=1000),
    session: Session = Depends(get_session),
) -> ShadowComparison:
    _check_service_key(request, service_key)
    evaluations = ShadowRepository(session).history(service_key, limit=limit)
    return ShadowService.compare(service_key, evaluations)


def _evaluation_values(record: ShadowEvaluationRecord) -> dict:
    values = {
        key: getattr(record, key)
        for key in (
            "id",
            "recommendation_id",
            "service_key",
            "current_policy_version",
            "current_rate",
            "proposed_rate",
            "actual_incoming_rps",
            "estimated_admitted_rps",
            "estimated_rejected_rps",
            "evaluation_window_seconds",
            "created_at",
        )
    }
    values.update(record.evaluation_result)
    return values
