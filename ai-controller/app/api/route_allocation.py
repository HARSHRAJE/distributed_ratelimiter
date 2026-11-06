from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.telemetry import get_session, require_internal_api_key
from app.route_allocation.allocation_service import RouteAllocationService
from app.route_allocation.resource_constraints import (
    RouteAllocationConstraintError,
)
from app.route_allocation.schemas import (
    RouteAllocationComparison,
    RouteAllocationConfig,
    RouteAllocationConfigList,
    RouteAllocationEvaluationRequest,
    RouteAllocationHistory,
    RouteAllocationRun,
)

router = APIRouter(
    prefix="/api/v1/allocation/routes",
    tags=["route-allocation"],
    dependencies=[Depends(require_internal_api_key)],
)


def _check_service_key(request: Request, service_key: str) -> None:
    if service_key not in request.app.state.settings.service_keys:
        raise HTTPException(status_code=404, detail="Service not found")


@router.put(
    "/{service_key}/configs",
    response_model=list[RouteAllocationConfig],
)
def replace_route_configs(
    service_key: str,
    payload: RouteAllocationConfigList,
    request: Request,
    session: Session = Depends(get_session),
) -> list[RouteAllocationConfig]:
    _check_service_key(request, service_key)
    try:
        return RouteAllocationService().replace_configs(
            service_key,
            payload,
            session=session,
        )
    except IntegrityError as error:
        session.rollback()
        raise HTTPException(
            status_code=409,
            detail="Route allocation configuration conflicts with stored data",
        ) from error


@router.post(
    "/{service_key}/evaluate",
    response_model=RouteAllocationRun,
)
def evaluate_route_allocations(
    service_key: str,
    payload: RouteAllocationEvaluationRequest,
    request: Request,
    session: Session = Depends(get_session),
) -> RouteAllocationRun:
    _check_service_key(request, service_key)
    try:
        return RouteAllocationService().evaluate(
            service_key,
            payload.backend_resource_budget,
            session=session,
        )
    except RouteAllocationConstraintError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except ValueError as error:
        session.rollback()
        raise HTTPException(status_code=422, detail=str(error)) from error
    except IntegrityError as error:
        session.rollback()
        raise HTTPException(
            status_code=409,
            detail="Route allocation conflicted with a concurrent update",
        ) from error


@router.get("/{service_key}", response_model=RouteAllocationRun)
def current_route_allocations(
    service_key: str,
    request: Request,
    session: Session = Depends(get_session),
) -> RouteAllocationRun:
    _check_service_key(request, service_key)
    result = RouteAllocationService.latest(service_key, session=session)
    if result is None:
        raise HTTPException(
            status_code=404,
            detail="Route allocation has not been evaluated",
        )
    return result


@router.get(
    "/{service_key}/history",
    response_model=RouteAllocationHistory,
)
def route_allocation_history(
    service_key: str,
    request: Request,
    limit: int = Query(default=100, ge=1, le=1000),
    session: Session = Depends(get_session),
) -> RouteAllocationHistory:
    _check_service_key(request, service_key)
    return RouteAllocationService.history(
        service_key,
        session=session,
        limit=limit,
    )


@router.get(
    "/{service_key}/comparison",
    response_model=RouteAllocationComparison,
)
def compare_route_allocations(
    service_key: str,
    request: Request,
    session: Session = Depends(get_session),
) -> RouteAllocationComparison:
    _check_service_key(request, service_key)
    comparison = RouteAllocationService.comparison(
        service_key,
        session=session,
    )
    if comparison is None:
        raise HTTPException(
            status_code=404,
            detail="At least two route allocation runs are required to compare",
        )
    return comparison
