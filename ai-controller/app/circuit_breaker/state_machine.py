from datetime import datetime, timedelta, timezone

from app.circuit_breaker.breaker_state import BreakerState


def recovery_ready(
    *,
    state: str,
    next_attempt_at: datetime | None,
    now: datetime,
) -> bool:
    if state != BreakerState.OPEN.value or next_attempt_at is None:
        return False
    return _utc(next_attempt_at) <= _utc(now)


def recovery_deadline(now: datetime, timeout_seconds: int) -> datetime:
    return now + timedelta(seconds=timeout_seconds)


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value
