import asyncio
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from app.telemetry.prometheus_client import PrometheusClient
from app.telemetry.schemas import DataQuality


@dataclass(frozen=True)
class CollectedTelemetry:
    id: UUID
    service_key: str
    timestamp: datetime
    window_seconds: int
    incoming_rps: float | None
    allowed_rps: float | None
    rejected_rps: float | None
    p95_latency_ms: float | None
    p99_latency_ms: float | None
    error_rate: float | None
    cpu_utilization: float | None
    memory_utilization: float | None
    redis_latency_ms: float | None
    queue_depth: float | None
    data_quality: DataQuality
    collected_at: datetime


class TelemetryCollector:
    def __init__(
        self,
        prometheus: PrometheusClient,
        *,
        stale_after_seconds: int = 60,
        collection_interval_seconds: int = 15,
    ) -> None:
        if stale_after_seconds < 1:
            raise ValueError("stale_after_seconds must be positive")
        self.prometheus = prometheus
        self.stale_after_seconds = stale_after_seconds
        self.collection_interval_seconds = collection_interval_seconds

    async def collect(
        self,
        service_key: str,
        *,
        now: datetime | None = None,
    ) -> CollectedTelemetry:
        collected_at = now or datetime.now(timezone.utc)
        expressions = self._expressions(service_key)
        names = list(expressions)
        results = await asyncio.gather(
            *(self.prometheus.query(expressions[name]) for name in names)
        )

        values: dict[str, float | None] = {}
        stale_names: set[str] = set()
        invalid_names: set[str] = set()
        for name, result in zip(names, results, strict=True):
            value, stale, invalid = self._read_value(
                result,
                now=collected_at,
            )
            values[name] = value
            if stale:
                stale_names.add(name)
            if invalid:
                invalid_names.add(name)

        present_count = sum(value is not None for value in values.values())
        if invalid_names:
            quality: DataQuality = "invalid"
        elif stale_names:
            quality = "stale"
        elif present_count == 0:
            quality = "missing"
        elif present_count < len(expressions):
            quality = "partial"
        else:
            quality = "valid"

        return CollectedTelemetry(
            id=uuid4(),
            service_key=service_key,
            timestamp=self._window_start(collected_at),
            window_seconds=self.collection_interval_seconds,
            incoming_rps=values["incoming_rps"],
            allowed_rps=values["allowed_rps"],
            rejected_rps=values["rejected_rps"],
            p95_latency_ms=values["p95_latency_ms"],
            p99_latency_ms=values["p99_latency_ms"],
            error_rate=values["error_rate"],
            cpu_utilization=values["cpu_utilization"],
            memory_utilization=values["memory_utilization"],
            redis_latency_ms=values["redis_latency_ms"],
            queue_depth=values["queue_depth"],
            data_quality=quality,
            collected_at=collected_at,
        )

    def _window_start(self, collected_at: datetime) -> datetime:
        epoch = int(collected_at.timestamp())
        aligned = epoch - epoch % self.collection_interval_seconds
        return datetime.fromtimestamp(aligned, tz=timezone.utc)

    @staticmethod
    def _expressions(service_key: str) -> dict[str, str]:
        label = service_key.replace("\\", "\\\\").replace('"', '\\"')
        app_label = f'application="{label}"'
        service_matcher = f'service="{label}"'
        return {
            "incoming_rps": (
                "sum(rate(ratelimit_requests_total"
                f"{{{service_matcher}}}[1m]))"
            ),
            "allowed_rps": (
                "sum(rate(ratelimit_requests_total"
                f'{{{service_matcher},outcome="allowed"}}[1m]))'
            ),
            "rejected_rps": (
                "sum(rate(ratelimit_requests_total"
                f'{{{service_matcher},outcome="rejected"}}[1m]))'
            ),
            "p95_latency_ms": (
                "1000 * histogram_quantile(0.95, "
                "sum by (le) (rate(http_server_requests_seconds_bucket"
                f"{{{app_label}}}[5m])))"
            ),
            "p99_latency_ms": (
                "1000 * histogram_quantile(0.99, "
                "sum by (le) (rate(http_server_requests_seconds_bucket"
                f"{{{app_label}}}[5m])))"
            ),
            "error_rate": (
                "sum(rate(http_server_requests_seconds_count"
                f'{{{app_label},status=~"5.."}}[1m])) or '
                "(0 * sum(http_server_requests_seconds_count"
                f"{{{app_label}}}))"
            ),
            "cpu_utilization": (
                f"100 * avg(process_cpu_usage{{{app_label}}})"
            ),
            "memory_utilization": (
                "100 * sum(jvm_memory_used_bytes"
                f'{{{app_label},area="heap"}}) / '
                "sum(jvm_memory_max_bytes"
                f'{{{app_label},area="heap"}} > 0)'
            ),
            "redis_latency_ms": (
                "1000 * histogram_quantile(0.95, "
                "sum by (le) (rate(ratelimit_redis_latency_seconds_bucket"
                '{operation="token_bucket"}[5m])))'
            ),
            "queue_depth": (
                'sum(policy_outbox_pending{application="policy-service"})'
            ),
        }

    def _read_value(
        self,
        result: list[dict[str, Any]],
        *,
        now: datetime,
    ) -> tuple[float | None, bool, bool]:
        if not result:
            return None, False, False
        if len(result) != 1:
            return None, False, True

        sample = result[0].get("value")
        if not isinstance(sample, list) or len(sample) != 2:
            return None, False, True

        try:
            timestamp = float(sample[0])
            value = float(sample[1])
        except (TypeError, ValueError, OverflowError):
            return None, False, True

        if not math.isfinite(timestamp):
            return None, False, True
        if math.isnan(value):
            return None, False, False
        if not math.isfinite(value):
            return None, False, True
        if value < 0:
            return None, False, True
        stale = now.timestamp() - timestamp > self.stale_after_seconds
        if timestamp - now.timestamp() > self.stale_after_seconds:
            return None, False, True
        if stale:
            return None, True, False
        return value, False, False
