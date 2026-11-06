from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.telemetry import get_session, require_internal_api_key
from app.sla_allocation.guarantee_validator import SlaGuaranteeError
from app.sla_allocation.schemas import (
    SlaEvaluationRequest,
    SlaAllocationHistory,
    SlaAllocationRun,
    SlaComplianceReport,
    TenantSlaConfig,
    TenantSlaConfigList,
)
from app.sla_allocation.sla_service import SlaService

router = APIRouter(
    prefix="/api/v1/sla",
    tags=["sla-allocation"],
    dependencies=[Depends(require_internal_api_key)],
)


def _check_service_key(request: Request, service_key: str) -> None:
    if service_key not in request.app.state.settings.service_keys:
        raise HTTPException(status_code=404, detail="Service not found")


@router.put(
    "/{service_key}/tenants",
    response_model=list[TenantSlaConfig],
)
def replace_sla_configs(
    service_key: str,
    payload: TenantSlaConfigList,
    request: Request,
    session: Session = Depends(get_session),
) -> list[TenantSlaConfig]:
    _check_service_key(request, service_key)
    try:
        return SlaService().replace_configs(
            service_key,
            payload,
            session=session,
        )
    except IntegrityError as error:
        session.rollback()
        raise HTTPException(
            status_code=409,
            detail="Tenant SLA configuration conflicts with stored data",
        ) from error


@router.post("/{service_key}/evaluate", response_model=SlaAllocationRun)
def evaluate_sla_allocation(
    service_key: str,
    payload: SlaEvaluationRequest,
    request: Request,
    session: Session = Depends(get_session),
) -> SlaAllocationRun:
    _check_service_key(request, service_key)
    try:
        return SlaService().evaluate(
            service_key,
            payload.global_service_capacity,
            session=session,
        )
    except SlaGuaranteeError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except IntegrityError as error:
        session.rollback()
        raise HTTPException(
            status_code=409,
            detail="SLA allocation conflicted with a concurrent update",
        ) from error


@router.get(
    "/{service_key}/tenants",
    response_model=list[TenantSlaConfig],
)
def list_sla_tenants(
    service_key: str,
    request: Request,
    session: Session = Depends(get_session),
) -> list[TenantSlaConfig]:
    _check_service_key(request, service_key)
    return SlaService.list_configs(service_key, session=session)


@router.get(
    "/{service_key}/tenants/{tenant_id}",
    response_model=TenantSlaConfig,
)
def get_sla_tenant(
    service_key: str,
    tenant_id: str,
    request: Request,
    session: Session = Depends(get_session),
) -> TenantSlaConfig:
    _check_service_key(request, service_key)
    config = SlaService.get_config(
        service_key,
        tenant_id,
        session=session,
    )
    if config is None:
        raise HTTPException(status_code=404, detail="Tenant SLA not found")
    return config


@router.get(
    "/{service_key}/compliance",
    response_model=SlaComplianceReport,
)
def sla_compliance(
    service_key: str,
    request: Request,
    session: Session = Depends(get_session),
) -> SlaComplianceReport:
    _check_service_key(request, service_key)
    return SlaService.compliance(service_key, session=session)


@router.get(
    "/{service_key}/allocation-history",
    response_model=SlaAllocationHistory,
)
def sla_allocation_history(
    service_key: str,
    request: Request,
    session: Session = Depends(get_session),
) -> SlaAllocationHistory:
    _check_service_key(request, service_key)
    return SlaService.history(
        service_key,
        session=session,
        limit=100,
    )
