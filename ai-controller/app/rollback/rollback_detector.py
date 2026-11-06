from app.config import Settings
from app.rollback.schemas import RollbackTrigger
from app.telemetry.models import TelemetrySampleRecord


class RollbackDetector:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def detect(
        self,
        windows: list[TelemetrySampleRecord],
        *,
        baseline: TelemetrySampleRecord | None,
    ) -> list[RollbackTrigger]:
        if not windows:
            return []

        triggers: list[RollbackTrigger] = []
        latest = windows[-1]
        self._consecutive_threshold(
            windows,
            field="p95_latency_ms",
            count=self.settings.rollback_p95_consecutive_windows,
            threshold=self.settings.rollback_p95_threshold_ms,
            metric="P95_LATENCY",
            label="p95 latency",
            triggers=triggers,
        )
        error_rates = [
            (
                _error_percent(item.error_rate, item.incoming_rps)
                if item.data_quality == "valid"
                else None
            )
            for item in windows
        ]
        self._consecutive_values(
            error_rates,
            count=self.settings.rollback_5xx_consecutive_windows,
            windows=windows,
            threshold=self.settings.rollback_5xx_threshold_percent,
            metric="5XX_ERROR_RATE",
            label="5xx error rate",
            triggers=triggers,
        )
        if (
            latest.data_quality == "valid"
            and latest.error_rate is not None
            and latest.incoming_rps
        ):
            current_5xx = _error_percent(
                latest.error_rate,
                latest.incoming_rps,
            )
            if current_5xx >= self.settings.rollback_critical_5xx_percent:
                triggers.append(
                    RollbackTrigger(
                        metric="5XX_ERROR_RATE",
                        value=current_5xx,
                        threshold=self.settings.rollback_critical_5xx_percent,
                        reason="Critical 5xx error rate requires immediate rollback",
                        critical=True,
                    )
                )
        self._consecutive_threshold(
            windows,
            field="cpu_utilization",
            count=self.settings.rollback_cpu_consecutive_windows,
            threshold=self.settings.rollback_cpu_threshold_percent,
            metric="CPU_UTILIZATION",
            label="CPU utilization",
            triggers=triggers,
        )
        self._queue_growth(windows, triggers)
        self._throughput_degradation(windows, baseline, triggers)

        return _deduplicate(triggers)

    @staticmethod
    def _consecutive_threshold(
        windows: list[TelemetrySampleRecord],
        *,
        field: str,
        count: int,
        threshold: float,
        metric: str,
        label: str,
        triggers: list[RollbackTrigger],
    ) -> None:
        selected = windows[-count:]
        values = [getattr(item, field) for item in selected]
        if (
            len(selected) == count
            and _windows_consecutive(selected)
            and all(item.data_quality == "valid" for item in selected)
            and all(value is not None and float(value) > threshold for value in values)
        ):
            triggers.append(
                RollbackTrigger(
                    metric=metric,
                    value=float(values[-1]),
                    threshold=threshold,
                    reason=(
                        f"{label} exceeded the configured threshold for "
                        f"{count} consecutive windows"
                    ),
                )
            )

    @staticmethod
    def _consecutive_values(
        values: list[float | None],
        *,
        count: int,
        windows: list[TelemetrySampleRecord],
        threshold: float,
        metric: str,
        label: str,
        triggers: list[RollbackTrigger],
    ) -> None:
        selected = values[-count:]
        selected_windows = windows[-count:]
        if (
            len(selected) == count
            and _windows_consecutive(selected_windows)
            and all(value is not None for value in selected)
            and all(value is not None and value > threshold for value in selected)
        ):
            triggers.append(
                RollbackTrigger(
                    metric=metric,
                    value=float(selected[-1]),
                    threshold=threshold,
                    reason=(
                        f"{label} exceeded the configured threshold for "
                        f"{count} consecutive windows"
                    ),
                )
            )

    def _queue_growth(
        self,
        windows: list[TelemetrySampleRecord],
        triggers: list[RollbackTrigger],
    ) -> None:
        count = self.settings.rollback_queue_growth_windows
        selected = windows[-count:]
        values = [item.queue_depth for item in selected]
        if (
            len(selected) == count
            and _windows_consecutive(selected)
            and all(item.data_quality == "valid" for item in selected)
            and all(value is not None for value in values)
            and all(float(value) > self.settings.rollback_queue_depth_threshold for value in values)
            and all(
                float(current) > float(previous)
                for previous, current in zip(values, values[1:])
            )
        ):
            triggers.append(
                RollbackTrigger(
                    metric="QUEUE_GROWTH",
                    value=float(values[-1]),
                    threshold=self.settings.rollback_queue_depth_threshold,
                    reason=(
                        "Queue depth exceeded its threshold and grew in each "
                        f"of {count} consecutive windows"
                    ),
                )
            )

    def _throughput_degradation(
        self,
        windows: list[TelemetrySampleRecord],
        baseline: TelemetrySampleRecord | None,
        triggers: list[RollbackTrigger],
    ) -> None:
        if (
            baseline is None
            or baseline.allowed_rps is None
            or baseline.incoming_rps is None
            or baseline.incoming_rps <= 0
        ):
            return
        baseline_acceptance = (
            float(baseline.allowed_rps) / float(baseline.incoming_rps)
        )
        if baseline_acceptance <= 0:
            return
        count = self.settings.rollback_throughput_consecutive_windows
        selected = windows[-count:]
        if len(selected) != count or not _windows_consecutive(selected) or any(
            item.allowed_rps is None
            or item.incoming_rps is None
            or item.incoming_rps <= 0
            or item.data_quality != "valid"
            for item in selected
        ):
            return
        drops = [
            max(
                0.0,
                (
                    baseline_acceptance
                    - float(item.allowed_rps) / float(item.incoming_rps)
                )
                / baseline_acceptance
                * 100,
            )
            for item in selected
        ]
        threshold = self.settings.rollback_throughput_drop_percent
        if all(value > threshold for value in drops):
            triggers.append(
                RollbackTrigger(
                    metric="THROUGHPUT_DEGRADATION",
                    value=drops[-1],
                    threshold=threshold,
                    reason=(
                        "Accepted throughput fell below its pre-change baseline "
                        f"for {count} consecutive windows"
                    ),
                )
            )


def _error_percent(error_rps: float | None, incoming_rps: float | None) -> float:
    if error_rps is None or incoming_rps is None or incoming_rps <= 0:
        return 0.0
    return float(error_rps) / float(incoming_rps) * 100


def _windows_consecutive(
    windows: list[TelemetrySampleRecord],
) -> bool:
    if len(windows) < 2:
        return True
    for previous, current in zip(windows, windows[1:]):
        elapsed = (
            current.window_start - previous.window_start
        ).total_seconds()
        maximum_gap = min(
            previous.window_seconds,
            current.window_seconds,
        ) * 1.5
        if elapsed <= 0 or elapsed > maximum_gap:
            return False
    return True


def _deduplicate(triggers: list[RollbackTrigger]) -> list[RollbackTrigger]:
    unique: dict[str, RollbackTrigger] = {}
    for trigger in triggers:
        existing = unique.get(trigger.metric)
        if existing is None or trigger.critical:
            unique[trigger.metric] = trigger
    return list(unique.values())
