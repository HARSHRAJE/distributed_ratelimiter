from sqlalchemy.orm import Session

from app.chaos.experiment_repository import ChaosExperimentRepository
from app.chaos.schemas import (
    ChaosExperiment,
    ChaosExperimentHistory,
    ChaosExperimentRequest,
)
from app.config import Settings

_IMPLEMENTED_SCENARIOS = {"CH-01"}


class UnsupportedChaosScenario(Exception):
    pass


class ChaosService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def enqueue(
        self,
        request: ChaosExperimentRequest,
        *,
        session: Session,
    ):
        if not self.settings.chaos_enabled:
            raise ValueError("Chaos testing is disabled")
        if (
            request.test_environment_id
            != self.settings.chaos_test_environment_id
        ):
            raise ValueError("Test environment identifier does not match")
        if request.service_key not in self.settings.service_keys:
            raise ValueError("Service is not configured")
        if request.experiment_code.value not in _IMPLEMENTED_SCENARIOS:
            raise UnsupportedChaosScenario(
                f"{request.experiment_code.value} is registered but not "
                "implemented; no fault can be scheduled"
            )
        if not self.settings.administrator_api_key:
            raise ValueError(
                "Chaos experiments require administrator authentication"
            )
        duration = (
            request.fault_duration_seconds
            or self.settings.chaos_fault_duration_seconds
        )
        if duration > self.settings.chaos_fault_duration_seconds:
            raise ValueError(
                "Requested fault duration exceeds the configured maximum"
            )
        return ChaosExperimentRepository(session).enqueue(
            request,
            fault_duration_seconds=duration,
        )

    def history(
        self,
        *,
        service_key: str | None,
        limit: int,
        session: Session,
    ) -> ChaosExperimentHistory:
        records = ChaosExperimentRepository(session).history(
            test_environment_id=self.settings.chaos_test_environment_id,
            service_key=service_key,
            limit=limit,
        )
        return ChaosExperimentHistory(
            experiments=[
                ChaosExperiment.model_validate(item) for item in records
            ]
        )
