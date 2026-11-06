from dataclasses import dataclass


@dataclass(frozen=True)
class RecoveryAssessment:
    recovered: bool
    recovery_time_ms: int | None
    details: dict


class RecoveryValidator:
    @staticmethod
    def assess(
        *,
        recovery_probe: dict | None,
        recovery_time_ms: int | None,
    ) -> RecoveryAssessment:
        recovered = (
            recovery_probe is not None
            and recovery_probe.get("status_code") in {200, 201, 202, 204, 429}
            and recovery_time_ms is not None
            and recovery_time_ms >= 0
        )
        return RecoveryAssessment(
            recovered=recovered,
            recovery_time_ms=recovery_time_ms if recovered else None,
            details={
                "recovery_probe": recovery_probe,
                "recovery_observed": recovered,
            },
        )
