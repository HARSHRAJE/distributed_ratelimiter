from dataclasses import dataclass
from datetime import datetime, timezone
import math
from typing import Sequence

from app.shadow.schemas import BucketConfiguration, TrafficPoint

MAX_SIMULATED_REQUESTS = 2_000_000


@dataclass(frozen=True)
class TokenBucket:
    capacity: int
    refill_rate_rps: float


@dataclass(frozen=True)
class SimulationResult:
    admitted_requests: int
    rejected_requests: int
    elapsed_seconds: float

    @property
    def admitted_rps(self) -> float:
        if self.elapsed_seconds <= 0:
            return 0.0
        return self.admitted_requests / self.elapsed_seconds

    @property
    def rejected_rps(self) -> float:
        if self.elapsed_seconds <= 0:
            return 0.0
        return self.rejected_requests / self.elapsed_seconds


def simulate_token_buckets(
    points: Sequence[TrafficPoint],
    *,
    global_bucket: TokenBucket,
    tenant_bucket: BucketConfiguration,
    route_bucket: BucketConfiguration,
    initial_tokens_full: bool = True,
) -> SimulationResult:
    """Replay uniform-within-window arrivals through the Gateway's 3 buckets."""
    if not points:
        raise ValueError("At least one telemetry point is required")
    ordered = sorted(points, key=lambda point: point.timestamp)
    elapsed_seconds = sum(point.window_seconds for point in ordered)
    request_total = sum(
        math.floor(point.incoming_rps * point.window_seconds + 0.5)
        for point in ordered
    )
    if request_total > MAX_SIMULATED_REQUESTS:
        raise ValueError(
            f"Shadow replay exceeds the {MAX_SIMULATED_REQUESTS} request limit"
        )

    buckets = [
        global_bucket,
        TokenBucket(
            tenant_bucket.capacity,
            tenant_bucket.refill_rate_rps,
        ),
        TokenBucket(
            route_bucket.capacity,
            route_bucket.refill_rate_rps,
        ),
    ]
    tokens = [
        float(bucket.capacity if initial_tokens_full else 0)
        for bucket in buckets
    ]
    previous_ms: int | None = None
    admitted = 0
    rejected = 0

    for point in ordered:
        start_ms = _as_utc(point.timestamp).timestamp() * 1000
        duration_ms = point.window_seconds * 1000
        request_count = math.floor(
            point.incoming_rps * point.window_seconds + 0.5
        )
        for request_index in range(request_count):
            event_ms = int(
                start_ms + (request_index * duration_ms / request_count)
            )
            if previous_ms is not None:
                elapsed_ms = max(0, event_ms - previous_ms)
                for index, bucket in enumerate(buckets):
                    tokens[index] = min(
                        float(bucket.capacity),
                        tokens[index] + bucket.refill_rate_rps * elapsed_ms / 1000,
                    )
            if all(available >= 1 for available in tokens):
                admitted += 1
                tokens = [available - 1 for available in tokens]
            else:
                rejected += 1
            previous_ms = event_ms

    return SimulationResult(
        admitted_requests=admitted,
        rejected_requests=rejected,
        elapsed_seconds=elapsed_seconds,
    )


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
