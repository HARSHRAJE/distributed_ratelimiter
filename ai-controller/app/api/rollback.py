from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from app.api.telemetry import get_session, require_internal_api_key
from app.execution.policy_client import PolicyClientError
from app.rollback.rollback_service import RollbackError, RollbackService
from app.rollback.schemas import (
    RollbackEvaluation,
    RollbackEvent,
    RollbackHistory,
)

router = APIRouter(
    prefix="/api/v1/rollback",
    tags=["rollback"],
    dependencies=[Depends(require_internal_api_key)],
)


def _check_service_key(request: Request, service_key: str) -> None:
    if service_key not in request.app.state.settings.service_keys:
        raise HTTPException(status_code=404, detail="Service not found")


@router.post("/evaluate/{service_key}", response_model=RollbackEvaluation)
def evaluate_rollback(
    service_key: str,
    request: Request,
    session: Session = Depends(get_session),
) -> RollbackEvaluation:
    _check_service_key(request, service_key)
    return RollbackService(request.app.state.settings).evaluate(
        service_key,
        session=session,
    )


@router.post("/execute/{execution_id}", response_model=RollbackEvent)
def execute_rollback(
    execution_id: UUID,
    request: Request,
    session: Session = Depends(get_session),
) -> RollbackEvent:
    try:
        return RollbackService(request.app.state.settings).execute(
            execution_id,
            session=session,
        )
    except RollbackError as error:
        message = str(error)
        status_code = 404 if message == "Execution not found" else 409
        raise HTTPException(status_code=status_code, detail=message) from error
    except PolicyClientError as error:
        raise HTTPException(status_code=502, detail=str(error)) from error


@router.get("/{service_key}/history", response_model=RollbackHistory)
def rollback_history(
    service_key: str,
    request: Request,
    limit: int = Query(default=100, ge=1, le=1000),
    session: Session = Depends(get_session),
) -> RollbackHistory:
    _check_service_key(request, service_key)
    return RollbackService.history(
        service_key,
        session=session,
        limit=limit,
    )


@router.get("/{rollback_id}", response_model=RollbackEvent)
def rollback_detail(
    rollback_id: UUID,
    request: Request,
    session: Session = Depends(get_session),
) -> RollbackEvent:
    try:
        return RollbackService(request.app.state.settings).get(
            rollback_id,
            session=session,
        )
    except RollbackError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
