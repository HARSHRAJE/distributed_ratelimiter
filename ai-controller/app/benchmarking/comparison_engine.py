from statistics import mean, stdev
import json

from app.benchmarking.schemas import (
    BenchmarkComparison,
    BenchmarkResult,
    BenchmarkRun,
    BenchmarkScenario,
    BenchmarkStrategy,
    BenchmarkSloThresholds,
    StrategyComparison,
)

_METRICS = (
    "incoming_rps",
    "accepted_rps",
    "successful_rps",
    "p50_latency_ms",
    "p95_latency_ms",
    "p99_latency_ms",
    "backend_p95_latency_ms",
    "rejection_ratio",
    "backend_error_ratio",
    "cpu_usage",
    "gateway_cpu_usage",
    "memory_usage",
    "gateway_memory_usage",
    "redis_latency_ms",
    "sla_violation_count",
    "fairness_index",
    "allocation_proposal_fairness_index",
    "policy_changes",
    "stabilization_time_seconds",
    "redis_commands_per_second",
    "redis_connection_count",
    "redis_memory_bytes",
    "redis_error_count",
    "forecast_mae",
    "forecast_wape",
    "recommendation_generation_ms",
    "policy_application_ms",
    "propagation_delay_ms",
    "oscillation_frequency",
    "dropped_iterations",
)


class ComparisonEngine:
    def compare(
        self,
        *,
        service_key: str,
        scenario: BenchmarkScenario,
        environment_id: str | None,
        runs: list[tuple[BenchmarkRun, BenchmarkResult]],
    ) -> BenchmarkComparison:
        workloads = {
            json.dumps(run.workload_parameters, sort_keys=True)
            for run, _ in runs
        }
        commits = {run.git_commit for run, _ in runs}
        script_versions = {run.k6_script_version for run, _ in runs}
        config_versions: dict[BenchmarkStrategy, set[str]] = {
            strategy: set() for strategy in BenchmarkStrategy
        }
        for run, _ in runs:
            config_versions[run.strategy].add(run.config_version)
        if (
            len(workloads) > 1
            or len(commits) > 1
            or len(script_versions) > 1
            or any(len(versions) > 1 for versions in config_versions.values())
        ):
            raise ValueError(
                "Compared runs must use identical workload, source, script, "
                "and per-strategy configuration versions"
            )
        grouped: dict[BenchmarkStrategy, list[BenchmarkResult]] = {
            strategy: [] for strategy in BenchmarkStrategy
        }
        threshold_sets = {
            run.slo_thresholds.model_dump_json()
            for run, _ in runs
        }
        if len(threshold_sets) > 1:
            raise ValueError(
                "Runs can only be compared when their SLO thresholds match"
            )
        thresholds = (
            BenchmarkSloThresholds.model_validate_json(next(iter(threshold_sets)))
            if threshold_sets
            else None
        )
        batch_ids = []
        for run, result in runs:
            grouped[run.strategy].append(result)
            if run.batch_id not in batch_ids:
                batch_ids.append(run.batch_id)
        summaries = []
        for strategy in BenchmarkStrategy:
            results = grouped[strategy]
            means = {}
            deviations = {}
            for metric in _METRICS:
                values = [
                    float(value)
                    for item in results
                    if (value := getattr(item, metric)) is not None
                ]
                means[metric] = mean(values) if values else None
                deviations[metric] = (
                    stdev(values) if len(values) > 1 else 0.0 if values else None
                )
            summaries.append(
                StrategyComparison(
                    strategy=strategy,
                    sample_count=len(results),
                    means=means,
                    standard_deviations=deviations,
                )
            )
        regressions, improvements = self._relative_to_static(summaries)
        slo_violations, slo_pass = self._evaluate_slo(
            summaries,
            thresholds,
        )
        metric_errors = {
            strategy.value: sorted(
                {
                    error
                    for result in grouped[strategy]
                    for error in result.metrics_collection_errors
                }
            )
            for strategy in BenchmarkStrategy
        }
        return BenchmarkComparison(
            service_key=service_key,
            scenario=scenario,
            environment_id=environment_id,
            slo_thresholds=thresholds,
            batch_ids=batch_ids,
            strategies=summaries,
            regressions_vs_static=regressions,
            improvements_vs_static=improvements,
            slo_violations=slo_violations,
            slo_pass=slo_pass,
            metrics_collection_errors=metric_errors,
            report="",
        )

    @staticmethod
    def _relative_to_static(
        summaries: list[StrategyComparison],
    ) -> tuple[list[str], list[str]]:
        baseline = next(
            (item for item in summaries if item.strategy == BenchmarkStrategy.STATIC),
            None,
        )
        if baseline is None or baseline.sample_count == 0:
            return [], []
        regressions: list[str] = []
        improvements: list[str] = []
        for candidate in summaries:
            if candidate.strategy == BenchmarkStrategy.STATIC or not candidate.sample_count:
                continue
            for metric in (
                "p95_latency_ms",
                "p99_latency_ms",
                "backend_error_ratio",
                "rejection_ratio",
                "sla_violation_count",
            ):
                current = candidate.means[metric]
                static = baseline.means[metric]
                if current is not None and static is not None and current > static:
                    regressions.append(
                        f"{candidate.strategy.value} worsened {metric} "
                        f"versus STATIC ({current:.4g} vs {static:.4g})"
                    )
            static_throughput = baseline.means["successful_rps"]
            current_throughput = candidate.means["successful_rps"]
            if (
                static_throughput is not None
                and current_throughput is not None
                and current_throughput < static_throughput
            ):
                regressions.append(
                    f"{candidate.strategy.value} reduced successful_rps "
                    f"versus STATIC ({current_throughput:.4g} vs "
                    f"{static_throughput:.4g})"
                )
            health_metrics = (
                "p95_latency_ms",
                "p99_latency_ms",
                "backend_p95_latency_ms",
                "backend_error_ratio",
                "rejection_ratio",
                "sla_violation_count",
                "cpu_usage",
                "gateway_cpu_usage",
                "memory_usage",
                "gateway_memory_usage",
                "redis_latency_ms",
                "redis_error_count",
            )
            non_regressing = all(
                candidate.means[name] is not None
                and baseline.means[name] is not None
                and candidate.means[name] <= baseline.means[name]
                for name in health_metrics
            )
            fairness = candidate.means["fairness_index"]
            baseline_fairness = baseline.means["fairness_index"]
            if fairness is not None and baseline_fairness is not None:
                non_regressing = (
                    non_regressing and fairness >= baseline_fairness
                )
            if (
                non_regressing
                and static_throughput is not None
                and current_throughput is not None
                and current_throughput > static_throughput
            ):
                improvements.append(
                    f"{candidate.strategy.value} increased successful_rps "
                    "without worsening measured latency, backend errors, or "
                    "SLA violations"
                )
        return regressions, improvements

    @staticmethod
    def _evaluate_slo(
        summaries: list[StrategyComparison],
        thresholds: BenchmarkSloThresholds | None,
    ) -> tuple[dict[str, list[str]], dict[str, bool]]:
        violations: dict[str, list[str]] = {}
        passes: dict[str, bool] = {}
        if thresholds is None:
            return violations, passes
        limits = {
            "p95_latency_ms": (
                "max_p95_latency_ms",
                thresholds.max_p95_latency_ms,
                lambda value, limit: value <= limit,
            ),
            "p99_latency_ms": (
                "max_p99_latency_ms",
                thresholds.max_p99_latency_ms,
                lambda value, limit: value <= limit,
            ),
            "backend_p95_latency_ms": (
                "max_p95_latency_ms",
                thresholds.max_p95_latency_ms,
                lambda value, limit: value <= limit,
            ),
            "backend_error_ratio": (
                "max_backend_error_ratio",
                thresholds.max_backend_error_ratio,
                lambda value, limit: value <= limit,
            ),
            "rejection_ratio": (
                "max_rejection_ratio",
                thresholds.max_rejection_ratio,
                lambda value, limit: value <= limit,
            ),
            "sla_violation_count": (
                "max_sla_violation_count",
                thresholds.max_sla_violation_count,
                lambda value, limit: value <= limit,
            ),
            "fairness_index": (
                "minimum_fairness_index",
                thresholds.minimum_fairness_index,
                lambda value, limit: value >= limit,
            ),
            "cpu_usage": (
                "max_cpu_usage_percent",
                thresholds.max_cpu_usage_percent,
                lambda value, limit: value <= limit,
            ),
            "gateway_cpu_usage": (
                "max_cpu_usage_percent",
                thresholds.max_cpu_usage_percent,
                lambda value, limit: value <= limit,
            ),
            "memory_usage": (
                "max_memory_usage_percent",
                thresholds.max_memory_usage_percent,
                lambda value, limit: value <= limit,
            ),
            "gateway_memory_usage": (
                "max_memory_usage_percent",
                thresholds.max_memory_usage_percent,
                lambda value, limit: value <= limit,
            ),
            "redis_latency_ms": (
                "max_redis_latency_ms",
                thresholds.max_redis_latency_ms,
                lambda value, limit: value <= limit,
            ),
            "redis_error_count": (
                "max_redis_error_count",
                thresholds.max_redis_error_count,
                lambda value, limit: value <= limit,
            ),
            "dropped_iterations": (
                "max_dropped_iterations",
                thresholds.max_dropped_iterations,
                lambda value, limit: value <= limit,
            ),
            "successful_rps": (
                "minimum_successful_rps",
                thresholds.minimum_successful_rps,
                lambda value, limit: value >= limit,
            ),
        }
        for summary in summaries:
            strategy_name = summary.strategy.value
            if summary.sample_count == 0:
                violations[strategy_name] = ["no completed measurements"]
                passes[strategy_name] = False
                continue
            issues = []
            for metric, (threshold_name, limit, predicate) in limits.items():
                value = summary.means[metric]
                if value is None:
                    issues.append(f"{metric} was not measured")
                elif not predicate(value, limit):
                    issues.append(
                        f"{metric}={value:.4g} violates {threshold_name}={limit:.4g}"
                    )
            violations[strategy_name] = issues
            passes[strategy_name] = not issues
        return violations, passes
