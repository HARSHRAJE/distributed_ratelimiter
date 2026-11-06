from dataclasses import dataclass

from app.config import Settings


@dataclass(frozen=True)
class BreakerConfig:
    failure_threshold: int
    recovery_timeout_seconds: int
    half_open_max_calls: int
    success_threshold: int
    recovery_max_change_percent: float

    @classmethod
    def from_settings(cls, settings: Settings) -> "BreakerConfig":
        return cls(
            failure_threshold=settings.breaker_failure_threshold,
            recovery_timeout_seconds=(
                settings.breaker_recovery_timeout_seconds
            ),
            half_open_max_calls=settings.breaker_half_open_max_calls,
            success_threshold=settings.breaker_success_threshold,
            recovery_max_change_percent=(
                settings.breaker_recovery_max_change_percent
            ),
        )
