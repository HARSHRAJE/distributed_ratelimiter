from collections.abc import Iterable
from datetime import datetime
from statistics import fmean

from app.telemetry.models import TelemetrySampleRecord


class TelemetryAggregator:
    def aggregate(
        self,
        service_key: str,
        samples: Iterable[TelemetrySampleRecord],
        *,
        window_start: datetime,
        window_seconds: int,
        collection_interval_seconds: int,
    ) -> dict[str, object]:
        sample_list = list(samples)
        expected_samples = max(
            1,
            window_seconds // collection_interval_seconds,
        )
        good_samples = sum(
            sample.data_quality in ("valid", "partial")
            for sample in sample_list
        )

        incoming = self._values(sample_list, "incoming_rps")
        allowed = self._values(sample_list, "allowed_rps")
        rejected = self._values(sample_list, "rejected_rps")
        p95 = self._values(sample_list, "p95_latency_ms")
        p99 = self._values(sample_list, "p99_latency_ms")
        errors = self._values(sample_list, "error_rate")

        return {
            "service_key": service_key,
            "window_start": window_start,
            "window_seconds": window_seconds,
            "mean_incoming_rps": self._mean(incoming),
            "max_incoming_rps": max(incoming) if incoming else None,
            "mean_allowed_rps": self._mean(allowed),
            "mean_rejected_rps": self._mean(rejected),
            "mean_p95_latency_ms": self._mean(p95),
            "max_p95_latency_ms": max(p95) if p95 else None,
            "mean_p99_latency_ms": self._mean(p99),
            "max_p99_latency_ms": max(p99) if p99 else None,
            "mean_error_rate": self._mean(errors),
            "missing_sample_count": max(expected_samples - good_samples, 0),
        }

    @staticmethod
    def _values(
        samples: list[TelemetrySampleRecord],
        field: str,
    ) -> list[float]:
        return [
            float(value)
            for sample in samples
            if sample.data_quality in ("valid", "partial")
            if (value := getattr(sample, field)) is not None
        ]

    @staticmethod
    def _mean(values: list[float]) -> float | None:
        return fmean(values) if values else None
