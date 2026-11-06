from dataclasses import dataclass
from datetime import datetime, timezone

from app.config import Settings
from app.rollback.rollback_detector import RollbackDetector
from app.rollback.schemas import RollbackTrigger
from app.telemetry.models import PolicyExecutionRecord, TelemetrySampleRecord


@dataclass(frozen=True)
class RollbackDecision:
    eligible: bool
    triggered: bool
    triggers: list[RollbackTrigger]
    message: str


class RollbackDecisionEngine:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.detector = RollbackDetector(settings)

    def decide(
        self,
        execution: PolicyExecutionRecord,
        windows: list[TelemetrySampleRecord],
        *,
        baseline: TelemetrySampleRecord | None,
        now: datetime,
    ) -> RollbackDecision:
        if execution.status == "SUBMITTED":
            age = (now - _utc(execution.started_at)).total_seconds()
            if age >= self.settings.rollback_redis_sync_timeout_seconds:
                trigger = RollbackTrigger(
                    metric="REDIS_SYNC",
                    value=age,
                    threshold=float(
                        self.settings.rollback_redis_sync_timeout_seconds
                    ),
                    reason=(
                        "Submitted service configuration did not become "
                        "effective within the configured timeout"
                    ),
                    critical=True,
                )
                return RollbackDecision(
                    True,
                    True,
                    [trigger],
                    "Redis synchronization timed out",
                )
            return RollbackDecision(
                True,
                False,
                [],
                "Waiting for Redis synchronization timeout",
            )

        if (
            execution.status != "APPLIED"
            or execution.resulting_version is None
            or execution.completed_at is None
        ):
            return RollbackDecision(
                False,
                False,
                [],
                "Latest service execution is not rollback eligible",
            )
        if not windows:
            return RollbackDecision(
                False,
                False,
                [],
                "No valid post-change telemetry is available",
            )
        triggers = self.detector.detect(windows, baseline=baseline)
        observation_age = (now - _utc(execution.completed_at)).total_seconds()
        if (
            observation_age < self.settings.rollback_observation_period_seconds
            and not any(trigger.critical for trigger in triggers)
        ):
            return RollbackDecision(
                True,
                False,
                [],
                "Minimum post-change observation period is active",
            )
        if triggers:
            return RollbackDecision(
                True,
                True,
                triggers,
                "Rollback trigger threshold met",
            )
        if sum(item.data_quality == "valid" for item in windows) < (
            self.settings.rollback_minimum_healthy_windows
        ):
            return RollbackDecision(
                True,
                False,
                [],
                "Insufficient healthy windows to evaluate rollback",
            )
        return RollbackDecision(
            True,
            False,
            [],
            "Service is healthy; no rollback trigger detected",
        )


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
