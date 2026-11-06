import hmac
from uuid import UUID

from fastapi import APIRouter, Body, Depends, Header, HTTPException, Query, Request
from sqlalchemy.orm import Session

from app.api.telemetry import get_session, require_internal_api_key
from app.config import Settings
from app.execution.execution_repository import ExecutionRepository
from app.execution.execution_service import ExecutionRejected, ExecutionService
from app.execution.policy_client import PolicyClient, PolicyClientError
from app.execution.rollout_manager import RolloutError, RolloutManager
from app.execution.schemas import (
    ExecutionHistory,
    ExecutionResult,
    ServiceControlRequest,
    ServiceControlResult,
)
from app.rollback.rollback_service import RollbackError, RollbackService

router = APIRouter(
    prefix="/api/v1/execution",
    tags=["execution"],
    dependencies=[Depends(require_internal_api_key)],
)


def _check_service_key(request: Request, service_key: str) -> None:
    if service_key not in request.app.state.settings.service_keys:
        raise HTTPException(status_code=404, detail="Service not found")


def _require_admin(
    request: Request,
    supplied_key: str | None,
) -> None:
    settings: Settings = request.app.state.settings
    expected_key = settings.administrator_api_key
    if len(expected_key) < 32:
        raise HTTPException(
            status_code=503,
            detail="Administrator authentication is not configured",
        )
    if supplied_key is None or not hmac.compare_digest(
        supplied_key,
        expected_key,
    ):
        raise HTTPException(status_code=401, detail="Unauthorized")


@router.post("/{recommendation_id}", response_model=ExecutionResult)
def execute_recommendation(
    recommendation_id: UUID,
    request: Request,
    session: Session = Depends(get_session),
) -> ExecutionResult:
    try:
        return ExecutionService(request.app.state.settings).execute(
            recommendation_id,
            session=session,
        )
    except ExecutionRejected as error:
        if str(error) == "Recommendation not found":
            raise HTTPException(status_code=404, detail=str(error)) from error
        raise HTTPException(
            status_code=409,
            detail={
                "message": str(error),
                "checks": [
                    check.model_dump(mode="json") for check in error.checks
                ],
            },
        ) from error
    except PolicyClientError as error:
        status_code = (
            503 if error.status_code is None else 502
        )
        raise HTTPException(
            status_code=status_code,
            detail=str(error),
        ) from error


@router.get("/{execution_id}", response_model=ExecutionResult)
def execution_status(
    execution_id: UUID,
    request: Request,
    session: Session = Depends(get_session),
) -> ExecutionResult:
    try:
        return ExecutionService(request.app.state.settings).get_status(
            execution_id,
            session=session,
        )
    except ExecutionRejected as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except PolicyClientError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error


@router.get("/{service_key}/history", response_model=ExecutionHistory)
def execution_history(
    service_key: str,
    request: Request,
    limit: int = Query(default=100, ge=1, le=1000),
    session: Session = Depends(get_session),
) -> ExecutionHistory:
    _check_service_key(request, service_key)
    return ExecutionHistory(
        service_key=service_key,
        executions=ExecutionService.history(
            service_key,
            session=session,
            limit=limit,
        ),
    )


@router.post(
    "/{service_key}/enable",
    response_model=ServiceControlResult,
)
def enable_service(
    service_key: str,
    request: Request,
    payload: ServiceControlRequest = Body(default=ServiceControlRequest()),
    admin_key: str | None = Header(default=None, alias="X-Admin-API-Key"),
    session: Session = Depends(get_session),
) -> ServiceControlResult:
    _require_admin(request, admin_key)
    _check_service_key(request, service_key)
    if payload.manual_override:
        raise HTTPException(
            status_code=422,
            detail="A manual override cannot be enabled for automatic execution",
        )
    try:
        RollbackService(request.app.state.settings).ensure_resume_allowed(
            service_key,
            session=session,
            manual_approval=payload.manual_approval,
        )
        return RolloutManager(request.app.state.settings).enable(
            service_key,
            repository=ExecutionRepository(session),
            client=PolicyClient(request.app.state.settings),
        )
    except RolloutError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except RollbackError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except PolicyClientError as error:
        raise HTTPException(status_code=502, detail=str(error)) from error


@router.post(
    "/{service_key}/disable",
    response_model=ServiceControlResult,
)
def disable_service(
    service_key: str,
    request: Request,
    payload: ServiceControlRequest = Body(default=ServiceControlRequest()),
    admin_key: str | None = Header(default=None, alias="X-Admin-API-Key"),
    session: Session = Depends(get_session),
) -> ServiceControlResult:
    _require_admin(request, admin_key)
    _check_service_key(request, service_key)
    try:
        return RolloutManager(request.app.state.settings).disable(
            service_key,
            manual_override=payload.manual_override,
            repository=ExecutionRepository(session),
            client=PolicyClient(request.app.state.settings),
        )
    except RolloutError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except PolicyClientError as error:
        raise HTTPException(status_code=502, detail=str(error)) from error


@router.post("/emergency/activate", response_model=dict[str, bool])
def activate_emergency_kill_switch(
    request: Request,
    admin_key: str | None = Header(default=None, alias="X-Admin-API-Key"),
    session: Session = Depends(get_session),
) -> dict[str, bool]:
    _require_admin(request, admin_key)
    manager = RolloutManager(request.app.state.settings)
    try:
        active = manager.set_global_kill_switch(
            active=True,
            repository=ExecutionRepository(session),
            client=PolicyClient(request.app.state.settings),
        )
    except PolicyClientError as error:
        raise HTTPException(status_code=502, detail=str(error)) from error
    return {"active": active}


@router.post("/emergency/deactivate", response_model=dict[str, bool])
def deactivate_emergency_kill_switch(
    request: Request,
    admin_key: str | None = Header(default=None, alias="X-Admin-API-Key"),
    session: Session = Depends(get_session),
) -> dict[str, bool]:
    _require_admin(request, admin_key)
    manager = RolloutManager(request.app.state.settings)
    try:
        active = manager.set_global_kill_switch(
            active=False,
            repository=ExecutionRepository(session),
            client=PolicyClient(request.app.state.settings),
        )
    except RolloutError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except PolicyClientError as error:
        raise HTTPException(status_code=502, detail=str(error)) from error
    return {"active": active}
