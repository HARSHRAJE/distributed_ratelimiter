import logging
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy.orm import sessionmaker

from app.chaos.experiment_repository import ChaosExperimentRepository
from app.chaos.fault_injector import FaultInjector
from app.chaos.recovery_validator import RecoveryValidator
from app.chaos.safety_validator import SafetyValidator
from app.config import Settings

LOGGER = logging.getLogger(__name__)


class ChaosExperimentRunner:
    def __init__(
        self,
        *,
        session_factory: sessionmaker,
        settings: Settings,
        fault_injector: FaultInjector | None = None,
    ) -> None:
        self.session_factory = session_factory
        self.settings = settings
        self.fault_injector = fault_injector or FaultInjector(settings)

    def claim_next(self):
        with self.session_factory() as session:
            return ChaosExperimentRepository(session).claim_next()

    async def run_once(self) -> UUID | None:
        record = self.claim_next()
        if record is None:
            return None
        experiment_id = record.id
        try:
            if record.experiment_code != "CH-01":
                raise ValueError(
                    f"{record.experiment_code} is not implemented yet; "
                    "no fault was injected"
                )
            if (
                record.test_environment_id
                != self.settings.chaos_test_environment_id
            ):
                raise ValueError(
                    "Experiment environment does not match local worker config"
                )
            observation = await self.fault_injector.inject_redis_unavailable(
                duration_seconds=record.fault_duration_seconds,
            )
            recovery = RecoveryValidator.assess(
                recovery_probe=observation.recovery_probe,
                recovery_time_ms=observation.recovery_time_ms,
            )
            safety = SafetyValidator().assess(
                fault_observations=observation.fault_probes,
                recovery_observations=(
                    [observation.recovery_probe]
                    if observation.recovery_probe is not None
                    else []
                ),
            )
            statuses = [
                item.get("status_code")
                for item in observation.fault_probes
                + (
                    [observation.recovery_probe]
                    if observation.recovery_probe is not None
                    else []
                )
            ]
            result = {
                "requests_sent": len(statuses),
                "accepted_requests": sum(
                    status in {200, 201, 202, 204} for status in statuses
                ),
                "rejected_requests": sum(status == 429 for status in statuses),
                "backend_errors": sum(
                    isinstance(status, int) and 500 <= status < 600
                    and status not in {502, 503, 504}
                    for status in statuses
                ),
                "gateway_errors": sum(
                    status in {502, 503, 504} or status is None
                    for status in statuses
                ),
                "policy_consistency": safety.policy_consistency,
                "recovery_success": (
                    recovery.recovered and observation.redis_restart_confirmed
                ),
                "recovery_time_ms": recovery.recovery_time_ms,
                "safety_violations": safety.safety_violations,
                "details": {
                    "fault_observations": observation.fault_probes,
                    "recovery": recovery.details,
                    "redis_restart_confirmed": (
                        observation.redis_restart_confirmed
                    ),
                    "safety_checks": safety.checks,
                    "policy_consistency_basis": (
                        "The Redis-unavailable injector does not write or "
                        "change policy state; explicit policy-version "
                        "regression checks require scenario-specific evidence."
                    ),
                    "policy_consistency_verified": (
                        safety.checks["policy_version_did_not_regress"]
                        is not None
                        and safety.checks[
                            "disabled_policy_was_not_resurrected"
                        ]
                        is not None
                    ),
                    "compose_events": observation.compose_events,
                },
            }
            with self.session_factory() as session:
                ChaosExperimentRepository(session).complete(
                    experiment_id,
                    result=result,
                    now=datetime.now(timezone.utc),
                )
        except Exception as error:
            LOGGER.error(
                "Chaos experiment failed: %s (%s)",
                experiment_id,
                type(error).__name__,
            )
            with self.session_factory() as session:
                ChaosExperimentRepository(session).fail(
                    experiment_id,
                    _safe_error(error),
                    now=datetime.now(timezone.utc),
                )
        return experiment_id


def _safe_error(error: Exception) -> str:
    if isinstance(error, ValueError):
        return str(error)[:2000]
    return f"Chaos experiment failed: {type(error).__name__}"
