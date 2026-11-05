from datetime import datetime, timezone

import pytest

from app.telemetry.collector import TelemetryCollector


class FakePrometheus:
    def __init__(self, timestamp: float, values: dict[str, str] | None = None):
        self.timestamp = timestamp
        self.values = values or {}
        self.queries: list[str] = []

    async def query(self, promql: str) -> list[dict]:
        self.queries.append(promql)
        if "rejected" in promql:
            value = self.values.get("rejected_rps", "2")
        elif "allowed" in promql:
            value = self.values.get("allowed_rps", "8")
        elif "ratelimit_requests_total" in promql:
            value = self.values.get("incoming_rps", "10")
        elif "0.95" in promql and "http_server" in promql:
            value = self.values.get("p95_latency_ms", "50")
        elif "0.99" in promql and "http_server" in promql:
            value = self.values.get("p99_latency_ms", "80")
        elif "status=~" in promql:
            value = self.values.get("error_rate", "0")
        elif "process_cpu_usage" in promql:
            value = self.values.get("cpu_utilization", "4")
        elif "jvm_memory_used_bytes" in promql:
            value = self.values.get("memory_utilization", "40")
        elif "redis_latency" in promql:
            value = self.values.get("redis_latency_ms", "2")
        else:
            value = self.values.get("queue_depth", "0")
        if value == "missing":
            return []
        return [{"value": [self.timestamp, value]}]


@pytest.mark.asyncio
async def test_collection_normalizes_valid_sample_and_aligns_window() -> None:
    now = datetime.fromtimestamp(1_700_000_007, tz=timezone.utc)
    prometheus = FakePrometheus(now.timestamp())
    sample = await TelemetryCollector(prometheus).collect(
        "orders-service",
        now=now,
    )

    assert sample.data_quality == "valid"
    assert sample.incoming_rps == 10
    assert sample.p95_latency_ms == 50
    assert sample.timestamp.timestamp() % 15 == 0
    assert len(prometheus.queries) == 10
    assert all("user_id" not in query for query in prometheus.queries)
    assert any(
        '{operation="token_bucket"}[5m]' in query
        for query in prometheus.queries
    )
    assert any(
        'status=~"5.."' in query and "or (0 * sum(" in query
        for query in prometheus.queries
    )


@pytest.mark.asyncio
async def test_missing_metric_is_partial_and_not_zero() -> None:
    now = datetime.now(timezone.utc)
    prometheus = FakePrometheus(
        now.timestamp(),
        {"incoming_rps": "missing"},
    )
    sample = await TelemetryCollector(prometheus).collect(
        "orders-service",
        now=now,
    )

    assert sample.data_quality == "partial"
    assert sample.incoming_rps is None


@pytest.mark.asyncio
async def test_all_missing_metrics_are_marked_missing() -> None:
    now = datetime.now(timezone.utc)
    sample = await TelemetryCollector(
        FakePrometheus(now.timestamp(), {
            "incoming_rps": "missing",
            "allowed_rps": "missing",
            "rejected_rps": "missing",
            "p95_latency_ms": "missing",
            "p99_latency_ms": "missing",
            "error_rate": "missing",
            "cpu_utilization": "missing",
            "memory_utilization": "missing",
            "redis_latency_ms": "missing",
            "queue_depth": "missing",
        })
    ).collect("orders-service", now=now)

    assert sample.data_quality == "missing"
    assert sample.incoming_rps is None
    assert sample.queue_depth is None


@pytest.mark.asyncio
async def test_stale_metrics_are_marked_stale_and_not_recorded_as_zero() -> None:
    now = datetime.now(timezone.utc)
    sample = await TelemetryCollector(
        FakePrometheus(now.timestamp() - 120),
        stale_after_seconds=60,
    ).collect("orders-service", now=now)

    assert sample.data_quality == "stale"
    assert sample.incoming_rps is None


@pytest.mark.asyncio
async def test_prometheus_nan_for_empty_histogram_is_missing() -> None:
    now = datetime.now(timezone.utc)
    sample = await TelemetryCollector(
        FakePrometheus(now.timestamp(), {"incoming_rps": "NaN"})
    ).collect("orders-service", now=now)

    assert sample.data_quality == "partial"
    assert sample.incoming_rps is None


@pytest.mark.asyncio
async def test_invalid_numeric_metric_is_marked_invalid() -> None:
    now = datetime.now(timezone.utc)
    sample = await TelemetryCollector(
        FakePrometheus(now.timestamp(), {"incoming_rps": "not-a-number"})
    ).collect("orders-service", now=now)

    assert sample.data_quality == "invalid"
    assert sample.incoming_rps is None
