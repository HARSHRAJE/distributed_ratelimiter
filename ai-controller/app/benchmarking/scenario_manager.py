from dataclasses import dataclass

from app.benchmarking.schemas import BenchmarkScenario, CapacityProfile


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
        capacity_profile: CapacityProfile | str | None = None,
    ) -> ScenarioPlan:
        duration = duration_seconds
        half = max(1, duration // 2)
        if capacity_profile is not None:
            profile = CapacityProfile(capacity_profile)
            if profile == CapacityProfile.BASELINE:
                return ScenarioPlan(
                    stages=[{"duration": duration, "target": start_rps}]
                )
            if profile == CapacityProfile.LOAD:
                return ScenarioPlan(
                    stages=[{"duration": duration, "target": peak_rps}]
                )
            if profile == CapacityProfile.STRESS:
                segment = duration // 4
                remainder = duration % 4
                stages = []
                for step in range(1, 5):
                    target = start_rps + (
                        (peak_rps - start_rps) * step + 3
                    ) // 4
                    stages.append({
                        "duration": segment + (1 if step <= remainder else 0),
                        "target": target,
                    })
                return ScenarioPlan(
                    stages=stages
                )
            if profile == CapacityProfile.SOAK:
                return ScenarioPlan(
                    stages=[{"duration": duration, "target": peak_rps}]
                )
            if profile == CapacityProfile.SPIKE:
                baseline = max(1, duration * 2 // 5)
                hold = max(1, duration // 5 - 2)
                recovery = duration - baseline - hold - 2
                return ScenarioPlan(
                    stages=[
                        {"duration": baseline, "target": start_rps},
                        {"duration": 1, "target": peak_rps},
                        {"duration": hold, "target": peak_rps},
                        {"duration": 1, "target": start_rps},
                        {"duration": recovery, "target": start_rps},
                    ],
                    recovery_start_seconds=baseline + hold + 2,
                )
            if profile == CapacityProfile.RECOVERY:
                peak_duration = max(1, duration // 5)
                recovery = duration - peak_duration - 1
                return ScenarioPlan(
                    stages=[
                        {"duration": peak_duration, "target": peak_rps},
                        {"duration": 1, "target": start_rps},
                        {"duration": recovery, "target": start_rps},
                    ],
                    recovery_start_seconds=peak_duration + 1,
                )
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
