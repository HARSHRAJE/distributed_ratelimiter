from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.allocation.allocation_constraints import AllocationConfigurationError
from app.allocation.allocation_service import AllocationService
from app.allocation.schemas import (
    AllocationEvaluationRequest,
    AllocationHistory,
    AllocationRun,
    TenantAllocationConfig,
    TenantAllocationConfigList,
)
from app.api.telemetry import get_session, require_internal_api_key

router = APIRouter(
    prefix="/api/v1/allocations",
    tags=["tenant-allocation"],
    dependencies=[Depends(require_internal_api_key)],
)


def _check_service_key(request: Request, service_key: str) -> None:
    if service_key not in request.app.state.settings.service_keys:
        raise HTTPException(status_code=404, detail="Service not found")


@router.put(
    "/{service_key}/tenants",
    response_model=list[TenantAllocationConfig],
)
def replace_tenant_configs(
    service_key: str,
    payload: TenantAllocationConfigList,
    request: Request,
    session: Session = Depends(get_session),
) -> list[TenantAllocationConfig]:
    _check_service_key(request, service_key)
    try:
        return AllocationService().save_configs(
            service_key,
            payload,
            session=session,
        )
    except IntegrityError as error:
        session.rollback()
        raise HTTPException(
            status_code=409,
            detail="Tenant allocation configuration conflicts with stored data",
        ) from error


@router.get(
    "/{service_key}/tenants",
    response_model=list[TenantAllocationConfig],
)
def get_tenant_configs(
    service_key: str,
    request: Request,
    session: Session = Depends(get_session),
) -> list[TenantAllocationConfig]:
    _check_service_key(request, service_key)
    return AllocationService().get_configs(service_key, session=session)


@router.post(
    "/evaluate/{service_key}",
    response_model=AllocationRun,
)
def evaluate_tenant_allocations(
    service_key: str,
    payload: AllocationEvaluationRequest,
    request: Request,
    session: Session = Depends(get_session),
) -> AllocationRun:
    _check_service_key(request, service_key)
    try:
        return AllocationService().evaluate(
            service_key,
            payload.global_capacity_rps,
            session=session,
        )
    except AllocationConfigurationError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except ValueError as error:
        session.rollback()
        raise HTTPException(status_code=422, detail=str(error)) from error
    except IntegrityError as error:
        session.rollback()
        raise HTTPException(
            status_code=409,
            detail="Allocation run conflicted with a concurrent update",
        ) from error


@router.get("/{service_key}/latest", response_model=AllocationRun)
def latest_tenant_allocation(
    service_key: str,
    request: Request,
    session: Session = Depends(get_session),
) -> AllocationRun:
    _check_service_key(request, service_key)
    result = AllocationService.latest(service_key, session=session)
    if result is None:
        raise HTTPException(status_code=404, detail="Allocation not found")
    return result


@router.get("/{service_key}/history", response_model=AllocationHistory)
def tenant_allocation_history(
    service_key: str,
    request: Request,
    limit: int = Query(default=100, ge=1, le=1000),
    session: Session = Depends(get_session),
) -> AllocationHistory:
    _check_service_key(request, service_key)
    return AllocationService.history(
        service_key,
        session=session,
        limit=limit,
    )
