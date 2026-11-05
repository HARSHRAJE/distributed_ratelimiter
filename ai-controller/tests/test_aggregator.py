from datetime import datetime, timezone
from types import SimpleNamespace

from app.telemetry.aggregator import TelemetryAggregator


def test_aggregates_measurements_and_counts_missing_slots() -> None:
    samples = [
        SimpleNamespace(
            data_quality="valid",
            incoming_rps=100,
            allowed_rps=90,
            rejected_rps=10,
            p95_latency_ms=20,
            p99_latency_ms=40,
            error_rate=1,
        ),
        SimpleNamespace(
            data_quality="partial",
            incoming_rps=200,
            allowed_rps=180,
            rejected_rps=20,
            p95_latency_ms=30,
            p99_latency_ms=50,
            error_rate=3,
        ),
        SimpleNamespace(
            data_quality="missing",
            incoming_rps=None,
            allowed_rps=None,
            rejected_rps=None,
            p95_latency_ms=None,
            p99_latency_ms=None,
            error_rate=None,
        ),
    ]

    result = TelemetryAggregator().aggregate(
        "orders-service",
        samples,
        window_start=datetime.now(timezone.utc),
        window_seconds=60,
        collection_interval_seconds=15,
    )

    assert result["mean_incoming_rps"] == 150
    assert result["max_incoming_rps"] == 200
    assert result["mean_allowed_rps"] == 135
    assert result["mean_rejected_rps"] == 15
    assert result["mean_p95_latency_ms"] == 25
    assert result["max_p99_latency_ms"] == 50
    assert result["mean_error_rate"] == 2
    assert result["missing_sample_count"] == 2


def test_empty_aggregation_does_not_invent_zero_measurements() -> None:
    result = TelemetryAggregator().aggregate(
        "orders-service",
        [],
        window_start=datetime.now(timezone.utc),
        window_seconds=60,
        collection_interval_seconds=15,
    )

    assert result["mean_incoming_rps"] is None
    assert result["max_p95_latency_ms"] is None
    assert result["missing_sample_count"] == 4
