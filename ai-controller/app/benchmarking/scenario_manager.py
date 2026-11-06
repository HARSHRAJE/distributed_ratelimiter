from dataclasses import dataclass

from app.benchmarking.schemas import BenchmarkScenario


@dataclass(frozen=True)
class ScenarioPlan:
    stages: list[dict[str, int | str]]
    hotspot: bool = False
    route_imbalance: bool = False
    operator_fault_required: bool = False
    recovery_start_seconds: int | None = None


class ScenarioManager:
    @staticmethod
    def build(
        scenario: BenchmarkScenario,
        *,
        duration_seconds: int,
        start_rps: int,
        peak_rps: int,
    ) -> ScenarioPlan:
        duration = duration_seconds
        half = max(1, duration // 2)
        if scenario == BenchmarkScenario.STEADY_TRAFFIC:
            stages = [{"duration": duration, "target": start_rps}]
        elif scenario == BenchmarkScenario.SUDDEN_SPIKE:
            baseline = max(1, duration // 3)
            spike_hold = max(1, duration // 3 - 1)
            recovery = duration - baseline - spike_hold - 2
            stages = [
                {"duration": baseline, "target": start_rps},
                {"duration": 1, "target": peak_rps},
                {"duration": spike_hold, "target": peak_rps},
                {"duration": 1, "target": start_rps},
                {"duration": recovery, "target": start_rps},
            ]
        elif scenario == BenchmarkScenario.GRADUAL_RAMP:
            stages = [
                {"duration": duration, "target": peak_rps},
            ]
        elif scenario == BenchmarkScenario.BURST_TRAFFIC:
            burst_duration = min(5, max(1, duration // 10))
            remaining = duration
            stages = []
            while remaining > 0:
                baseline = min(max(1, duration // 4), remaining)
                stages.append({"duration": baseline, "target": start_rps})
                remaining -= baseline
                if remaining > 0:
                    burst = min(burst_duration, remaining)
                    stages.append({"duration": burst, "target": peak_rps})
                    remaining -= burst
        elif scenario == BenchmarkScenario.TENANT_HOTSPOT:
            stages = [{"duration": duration, "target": start_rps}]
        elif scenario == BenchmarkScenario.ROUTE_IMBALANCE:
            stages = [{"duration": duration, "target": start_rps}]
        elif scenario in {
            BenchmarkScenario.BACKEND_DEGRADATION,
            BenchmarkScenario.REDIS_FAILURE,
            BenchmarkScenario.CONTROLLER_FAILURE,
            BenchmarkScenario.POLICY_SYNC_DELAY,
        }:
            stages = [{"duration": duration, "target": start_rps}]
        else:
            raise ValueError(f"Unsupported benchmark scenario: {scenario}")
        return ScenarioPlan(
            stages=stages,
            hotspot=scenario == BenchmarkScenario.TENANT_HOTSPOT,
            route_imbalance=scenario == BenchmarkScenario.ROUTE_IMBALANCE,
            operator_fault_required=scenario in {
                BenchmarkScenario.BACKEND_DEGRADATION,
                BenchmarkScenario.REDIS_FAILURE,
                BenchmarkScenario.CONTROLLER_FAILURE,
                BenchmarkScenario.POLICY_SYNC_DELAY,
            },
            recovery_start_seconds=(
                baseline + spike_hold + 2
                if scenario == BenchmarkScenario.SUDDEN_SPIKE
                else None
            ),
        )
