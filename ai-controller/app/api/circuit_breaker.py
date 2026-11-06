import hmac

from fastapi import APIRouter, Body, Depends, Header, HTTPException, Query, Request
from sqlalchemy.orm import Session

from app.api.telemetry import get_session, require_internal_api_key
from app.config import Settings
from app.circuit_breaker.breaker_service import BreakerService
from app.circuit_breaker.repository import BreakerRejected
from app.circuit_breaker.schemas import (
    BreakerHistory,
    BreakerStatus,
    ManualOpenRequest,
    ManualRecoveryRequest,
)
from app.execution.policy_client import PolicyClientError

router = APIRouter(
    prefix="/api/v1/circuit-breaker",
    tags=["circuit-breaker"],
    dependencies=[Depends(require_internal_api_key)],
)


def _check_service_key(request: Request, service_key: str) -> None:
    if service_key not in request.app.state.settings.service_keys:
        raise HTTPException(status_code=404, detail="Service not found")


def _require_admin(request: Request, supplied_key: str | None) -> None:
    settings: Settings = request.app.state.settings
    expected_key = settings.administrator_api_key
    if len(expected_key) < 32:
        raise HTTPException(
            status_code=503,
            detail="Administrator authentication is not configured",
        )
    if supplied_key is None or not hmac.compare_digest(supplied_key, expected_key):
        raise HTTPException(status_code=401, detail="Unauthorized")


@router.get("/{service_key}", response_model=BreakerStatus)
def get_breaker_state(
    service_key: str,
    request: Request,
    session: Session = Depends(get_session),
) -> BreakerStatus:
    _check_service_key(request, service_key)
    return BreakerService(request.app.state.settings).status(
        service_key,
        session=session,
    )


@router.post("/{service_key}/open", response_model=BreakerStatus)
def manually_open_breaker(
    service_key: str,
    request: Request,
    payload: ManualOpenRequest = Body(default=ManualOpenRequest()),
    admin_key: str | None = Header(default=None, alias="X-Admin-API-Key"),
    session: Session = Depends(get_session),
) -> BreakerStatus:
    _require_admin(request, admin_key)
    _check_service_key(request, service_key)
    return BreakerService(request.app.state.settings).manual_open(
        service_key,
        payload.reason,
        session=session,
    )


@router.post("/{service_key}/reset", response_model=BreakerStatus)
def request_breaker_recovery(
    service_key: str,
    request: Request,
    payload: ManualRecoveryRequest = Body(default=ManualRecoveryRequest()),
    admin_key: str | None = Header(default=None, alias="X-Admin-API-Key"),
    session: Session = Depends(get_session),
) -> BreakerStatus:
    _require_admin(request, admin_key)
    _check_service_key(request, service_key)
    try:
        return BreakerService(request.app.state.settings).request_recovery(
            service_key,
            clear_manual_disable=payload.clear_manual_disable,
            session=session,
            session_factory=request.app.state.session_factory,
        )
    except (ValueError, BreakerRejected) as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except PolicyClientError as error:
        raise HTTPException(status_code=502, detail=str(error)) from error


@router.get("/{service_key}/history", response_model=BreakerHistory)
def breaker_history(
    service_key: str,
    request: Request,
    limit: int = Query(default=100, ge=1, le=1000),
    session: Session = Depends(get_session),
) -> BreakerHistory:
    _check_service_key(request, service_key)
    return BreakerService.history(
        service_key,
        session=session,
        settings=request.app.state.settings,
        limit=limit,
    )
