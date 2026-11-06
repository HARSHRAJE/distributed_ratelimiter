from datetime import datetime, timezone

from app.telemetry.models import TelemetrySampleRecord


def telemetry_is_fresh(
    sample: TelemetrySampleRecord | None,
    *,
    now: datetime,
    maximum_age_seconds: int,
) -> bool:
    if sample is None or sample.data_quality not in {"valid", "partial"}:
        return False
    timestamp = sample.collected_at
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    current_time = now
    if current_time.tzinfo is None:
        current_time = current_time.replace(tzinfo=timezone.utc)
    age = (current_time - timestamp).total_seconds()
    return 0 <= age <= maximum_age_seconds
