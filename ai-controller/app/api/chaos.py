import hmac
from uuid import UUID

from fastapi import (
    APIRouter,
    Depends,
    Header,
    HTTPException,
    Query,
    Request,
    status,
)
from sqlalchemy.orm import Session

from app.api.telemetry import get_session, require_internal_api_key
from app.chaos.chaos_service import (
    ChaosService,
    UnsupportedChaosScenario,
)
from app.chaos.experiment_models import ChaosExperimentRecord
from app.chaos.experiment_repository import ChaosExperimentRepository
from app.chaos.schemas import (
    ChaosExperimentDetails,
    ChaosExperimentHistory,
    ChaosExperimentRequest,
    ChaosExperimentResult,
)
from app.config import Settings
from app.security.audit import record_security_event

router = APIRouter(
    prefix="/api/v1/chaos",
    tags=["chaos-testing"],
    dependencies=[Depends(require_internal_api_key)],
)


def _require_admin(
    request: Request,
    supplied_key: str | None,
) -> None:
    settings: Settings = request.app.state.settings
    expected = settings.administrator_api_key
    if len(expected) < 32:
        raise HTTPException(
            status_code=503,
            detail="Chaos administrator authentication is not configured",
        )
    if supplied_key is None or not hmac.compare_digest(supplied_key, expected):
        raise HTTPException(status_code=401, detail="Unauthorized")


@router.post(
    "/experiments",
    response_model=ChaosExperimentDetails,
    status_code=status.HTTP_202_ACCEPTED,
)
def create_experiment(
    payload: ChaosExperimentRequest,
    request: Request,
    admin_key: str | None = Header(
        default=None,
        alias="X-Admin-API-Key",
    ),
    session: Session = Depends(get_session),
) -> ChaosExperimentDetails:
    _require_admin(request, admin_key)
    try:
        experiment = ChaosService(request.app.state.settings).enqueue(
            payload,
            session=session,
        )
    except UnsupportedChaosScenario as error:
        raise HTTPException(status_code=501, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    record_security_event(
        session,
        actor_id="ADMIN_API_KEY",
        tenant_id=None,
        service_key=payload.service_key,
        event_type="CHAOS_EXPERIMENT_QUEUED",
        resource_id=str(experiment.id),
        outcome="QUEUED",
        source_ip=request.client.host if request.client is not None else None,
        details={"experiment_code": payload.experiment_code.value},
    )
    return ChaosExperimentDetails(experiment=experiment, result=None)


@router.get(
    "/experiments/history",
    response_model=ChaosExperimentHistory,
)
def experiment_history(
    request: Request,
    service_key: str | None = Query(default=None, min_length=1, max_length=100),
    limit: int = Query(default=100, ge=1, le=1000),
    session: Session = Depends(get_session),
) -> ChaosExperimentHistory:
    settings: Settings = request.app.state.settings
    if not settings.chaos_test_environment_id:
        raise HTTPException(
            status_code=503,
            detail="Chaos test environment is not configured",
        )
    if service_key is not None and service_key not in settings.service_keys:
        raise HTTPException(status_code=404, detail="Service not found")
    return ChaosService(settings).history(
        service_key=service_key,
        limit=limit,
        session=session,
    )


@router.get(
    "/experiments/{experiment_id}/results",
    response_model=ChaosExperimentResult,
)
def experiment_results(
    experiment_id: UUID,
    request: Request,
    session: Session = Depends(get_session),
) -> ChaosExperimentResult:
    record = ChaosExperimentRepository(session).get(experiment_id)
    _check_visible_experiment(request, record)
    result = ChaosExperimentRepository(session).result(experiment_id)
    if result is None:
        raise HTTPException(
            status_code=409,
            detail=f"Experiment result is not available (status: {record.status})",
        )
    return ChaosExperimentResult.model_validate(result)


@router.get(
    "/experiments/{experiment_id}",
    response_model=ChaosExperimentDetails,
)
def experiment_details(
    experiment_id: UUID,
    request: Request,
    session: Session = Depends(get_session),
) -> ChaosExperimentDetails:
    record = ChaosExperimentRepository(session).get(experiment_id)
    _check_visible_experiment(request, record)
    result = ChaosExperimentRepository(session).result(experiment_id)
    return ChaosExperimentDetails(
        experiment=record,
        result=(
            ChaosExperimentResult.model_validate(result)
            if result is not None
            else None
        ),
    )


def _check_visible_experiment(
    request: Request,
    record: ChaosExperimentRecord | None,
) -> None:
    if record is None:
        raise HTTPException(status_code=404, detail="Experiment not found")
    settings: Settings = request.app.state.settings
    if (
        record.test_environment_id != settings.chaos_test_environment_id
        or record.service_key not in settings.service_keys
    ):
        raise HTTPException(status_code=404, detail="Experiment not found")
