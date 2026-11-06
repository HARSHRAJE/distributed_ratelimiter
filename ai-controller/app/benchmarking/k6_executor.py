import asyncio
import json
import math
import os
import tempfile
from pathlib import Path
from urllib.parse import urlparse

from app.benchmarking.schemas import BenchmarkMetrics, BenchmarkRun
from app.benchmarking.scenario_manager import ScenarioManager

K6_SCRIPT_VERSION = "1"
_SCRIPT_PATH = Path(__file__).parent / "k6" / "scenarios.js"


class K6ExecutionError(RuntimeError):
    pass


class K6Executor:
    def __init__(
        self,
        *,
        binary: str,
        target_url: str,
        allowed_hosts: tuple[str, ...],
        route_paths: tuple[str, ...] = ("/",),
        tenant_tokens: tuple[str, ...] = (),
    ) -> None:
        self.binary = binary
        self.target_url = target_url
        self.allowed_hosts = allowed_hosts
        self.route_paths = route_paths
        self.tenant_tokens = tenant_tokens

    def _validate_target(self) -> None:
        parsed = urlparse(self.target_url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise K6ExecutionError("Benchmark target URL is not configured")
        try:
            port = parsed.port or (443 if parsed.scheme == "https" else 80)
        except ValueError as error:
            raise K6ExecutionError(
                "Benchmark target URL has an invalid port"
            ) from error
        target = f"{parsed.hostname.lower()}:{port}"
        if target not in {item.lower() for item in self.allowed_hosts}:
            raise K6ExecutionError(
                "Benchmark target host and port are not in the local test "
                "allowlist"
            )
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise K6ExecutionError(
                "Benchmark target URL must not contain credentials or query data"
            )

    async def execute(self, run: BenchmarkRun) -> BenchmarkMetrics:
        self._validate_target()
        plan = ScenarioManager.build(
            run.scenario,
            duration_seconds=run.duration_seconds,
            start_rps=run.start_rps,
            peak_rps=run.peak_rps,
            capacity_profile=run.workload_parameters.get("capacity_profile"),
        )
        if run.warmup_seconds:
            await self._execute_phase(
                run,
                stages=[
                    {
                        "duration": run.warmup_seconds,
                        "target": run.start_rps,
                    }
                ],
                summary_path=None,
                phase="warmup",
            )
        with tempfile.TemporaryDirectory(prefix="ai-controller-k6-") as workdir:
            summary_path = str(Path(workdir) / "summary.json")
            stopped_by_threshold = await self._execute_phase(
                run,
                stages=plan.stages,
                summary_path=summary_path,
                phase="measurement",
            )
            try:
                with open(summary_path, encoding="utf-8") as summary_file:
                    summary = json.load(summary_file)
            except (OSError, json.JSONDecodeError) as error:
                raise K6ExecutionError(
                    "k6 did not produce a valid summary"
                ) from error
        metrics = self._metrics_from_summary(summary, run.duration_seconds)
        if stopped_by_threshold:
            metrics.metrics_collection_errors.append(
                "k6 stress profile stopped early after a configured SLO "
                "threshold breach"
            )
        return metrics

    async def _execute_phase(
        self,
        run: BenchmarkRun,
        *,
        stages: list[dict[str, int | str]],
        summary_path: str | None,
        phase: str,
    ) -> bool:
        env = os.environ.copy()
        env.update(
            {
                "BENCHMARK_TARGET_URL": self.target_url,
                "BENCHMARK_STAGES": json.dumps(stages),
                "BENCHMARK_START_RPS": str(run.start_rps),
                "BENCHMARK_PEAK_RPS": str(run.peak_rps),
                "BENCHMARK_TENANT_COUNT": str(run.tenant_count),
                "BENCHMARK_SCENARIO": run.scenario.value,
                "BENCHMARK_STRATEGY": run.strategy.value,
                "BENCHMARK_CONFIG_VERSION": run.config_version,
                "BENCHMARK_HOTSPOT": str(
                    run.scenario.value == "TENANT_HOTSPOT"
                ).lower(),
                "BENCHMARK_ROUTE_IMBALANCE": str(
                    run.scenario.value == "ROUTE_IMBALANCE"
                ).lower(),
                "BENCHMARK_ROUTE_PATHS": ",".join(self.route_paths),
                "BENCHMARK_TENANT_TOKENS": json.dumps(
                    self.tenant_tokens
                ),
                "BENCHMARK_STRESS_PROFILE": str(
                    phase == "measurement"
                    and run.workload_parameters.get("capacity_profile")
                    == "STRESS"
                ).lower(),
                "BENCHMARK_STRESS_MAX_P95_MS": str(
                    run.slo_thresholds.max_p95_latency_ms
                ),
                "BENCHMARK_STRESS_MAX_P99_MS": str(
                    run.slo_thresholds.max_p99_latency_ms
                ),
                "BENCHMARK_STRESS_MAX_5XX_RATIO": str(
                    run.slo_thresholds.max_backend_error_ratio
                ),
                "BENCHMARK_STRESS_MAX_429_RATIO": str(
                    run.slo_thresholds.max_rejection_ratio
                ),
            }
        )
        command = [self.binary, "run", "--quiet"]
        if summary_path:
            command.extend(["--summary-export", summary_path])
        command.append(str(_SCRIPT_PATH))
        try:
            process = await asyncio.create_subprocess_exec(
                *command,
                env=env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except OSError as error:
            raise K6ExecutionError(
                "Unable to start k6; install k6 in the benchmark worker"
            ) from error

        timeout = max(60, run.duration_seconds + run.warmup_seconds + 120)
        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=timeout,
            )
        except TimeoutError as error:
            process.kill()
            await process.wait()
            raise K6ExecutionError("k6 benchmark exceeded its timeout") from error
        if process.returncode != 0:
            if (
                process.returncode == 99
                and phase == "measurement"
                and summary_path is not None
                and Path(summary_path).is_file()
            ):
                return True
            detail = (stderr or stdout).decode(errors="replace")[-500:]
            raise K6ExecutionError(
                f"k6 {phase} phase failed with exit code "
                f"{process.returncode}: {detail.strip()}"
            )
        return False

    @staticmethod
    def _metrics_from_summary(
        summary: dict,
        duration_seconds: int,
    ) -> BenchmarkMetrics:
        metrics = summary.get("metrics")
        if not isinstance(metrics, dict) or duration_seconds < 1:
            raise K6ExecutionError("k6 summary is missing measurement metrics")

        def values(name: str) -> dict:
            metric = metrics.get(name)
            result = metric.get("values") if isinstance(metric, dict) else None
            return result if isinstance(result, dict) else {}

        def number(value) -> float | None:
            try:
                parsed = float(value)
            except (ValueError, TypeError, OverflowError):
                return None
            return parsed if math.isfinite(parsed) else None

        requests = values("http_reqs")
        total_requests = number(requests.get("count")) or 0
        if total_requests <= 0:
            raise K6ExecutionError("k6 completed without issuing any requests")
        limited = number(
            values("benchmark_rate_limited_requests").get("count")
        ) or 0
        backend_errors = number(
            values("benchmark_backend_errors").get("count")
        ) or 0
        mismatches = number(
            values("benchmark_strategy_mismatches").get("count")
        ) or 0
        if mismatches > 0:
            raise K6ExecutionError(
                "Benchmark target did not confirm the requested strategy "
                "and configuration version on every response"
            )
        accepted = number(
            values("benchmark_accepted_requests").get("count")
        ) or 0
        accepted_rate = number(
            values("benchmark_accepted_requests").get("rate")
        )
        dropped_iterations = number(
            values("dropped_iterations").get("count")
        )
        successful = number(
            values("benchmark_successful_requests").get("count")
        ) or 0
        successful_rate = number(
            values("benchmark_successful_requests").get("rate")
        )
        fairness_details = _tenant_fairness_details(
            metrics,
            duration_seconds=duration_seconds,
        )
        fulfillment = [
            item["accepted_rps"] / item["demand_rps"]
            for item in fairness_details.values()
            if item["demand_rps"] > 0
        ]
        fairness = (
            sum(fulfillment) ** 2
            / (len(fulfillment) * sum(value * value for value in fulfillment))
            if fulfillment and any(fulfillment)
            else None
        )
        return BenchmarkMetrics(
            incoming_rps=number(requests.get("rate")),
            accepted_rps=(
                accepted_rate
                if accepted_rate is not None
                else accepted / duration_seconds
            ),
            successful_rps=(
                successful_rate
                if successful_rate is not None
                else successful / duration_seconds
            ),
            p50_latency_ms=number(
                values("benchmark_accepted_latency_ms").get("med")
            ),
            p95_latency_ms=number(
                values("benchmark_accepted_latency_ms").get("p(95)")
            ),
            p99_latency_ms=number(
                values("benchmark_accepted_latency_ms").get("p(99)")
            ),
            backend_p95_latency_ms=number(
                values("benchmark_backend_latency_ms").get("p(95)")
            ),
            rejection_ratio=limited / total_requests if total_requests else None,
            backend_error_ratio=(
                backend_errors / accepted if accepted else None
            ),
            fairness_index=fairness,
            fairness_basis=(
                "request_admission_by_tenant" if fairness is not None else None
            ),
            tenant_fairness_details=fairness_details or None,
            dropped_iterations=(
                int(dropped_iterations)
                if dropped_iterations is not None
                else 0
            ),
        )


def _tenant_fairness_details(
    metrics: dict,
    *,
    duration_seconds: int,
) -> dict[str, dict[str, float]]:
    demands = _tenant_counter_values(metrics, "benchmark_tenant_demand")
    accepted = _tenant_counter_values(metrics, "benchmark_tenant_accepted")
    return {
        tenant_id: {
            "demand_rps": demand / duration_seconds,
            "accepted_rps": accepted.get(tenant_id, 0.0) / duration_seconds,
            "demand_fulfillment_ratio": (
                min(1.0, accepted.get(tenant_id, 0.0) / demand)
                if demand > 0
                else 0.0
            ),
        }
        for tenant_id, demand in demands.items()
    }


def _tenant_counter_values(metrics: dict, prefix: str) -> dict[str, float]:
    result = {}
    for metric_name, metric in metrics.items():
        marker = f"{prefix}{{tenant_id:"
        if not metric_name.startswith(marker) or not isinstance(metric, dict):
            continue
        tenant_id = metric_name[len(marker):].split("}", 1)[0].split(",", 1)[0]
        values = metric.get("values")
        if not tenant_id or not isinstance(values, dict):
            continue
        count = values.get("count")
        try:
            parsed = float(count)
        except (ValueError, TypeError, OverflowError):
            continue
        if math.isfinite(parsed) and parsed >= 0:
            result[tenant_id] = parsed
    return result
