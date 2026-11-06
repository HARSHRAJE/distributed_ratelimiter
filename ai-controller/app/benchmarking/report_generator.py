from app.benchmarking.schemas import BenchmarkComparison


class ReportGenerator:
    @staticmethod
    def generate(comparison: BenchmarkComparison) -> BenchmarkComparison:
        available = [
            f"{item.strategy.value}: {item.sample_count} completed run(s)"
            for item in comparison.strategies
            if item.sample_count
        ]
        missing = [
            item.strategy.value
            for item in comparison.strategies
            if not item.sample_count
        ]
        lines = [
            f"Scenario {comparison.scenario.value} for "
            f"{comparison.service_key}.",
            "Compared results are measurements, not assumed improvements.",
        ]
        lines.extend(available or ["No completed runs are available."])
        if any(
            0 < item.sample_count < 3
            for item in comparison.strategies
            if item.sample_count
        ):
            lines.append(
                "Fewer than three repeats are available for at least one "
                "strategy; variability estimates are inconclusive."
            )
        if any(item.sample_count for item in comparison.strategies):
            lines.append(
                "Unavailable metrics are retained as null and cause the "
                "corresponding SLO check to fail."
            )
        for strategy, passed in comparison.slo_pass.items():
            lines.append(
                f"{strategy} {'PASSED' if passed else 'FAILED'} the supplied "
                "backend SLO thresholds."
            )
            lines.extend(
                f"{strategy} SLO: {issue}"
                for issue in comparison.slo_violations.get(strategy, [])
            )
        for strategy, errors in comparison.metrics_collection_errors.items():
            lines.extend(
                f"{strategy} metric collection: {error}"
                for error in errors
            )
        if missing:
            lines.append(
                "No completed measurements for: " + ", ".join(missing) + "."
            )
        lines.extend(comparison.regressions_vs_static)
        lines.extend(comparison.improvements_vs_static)
        if not comparison.regressions_vs_static and not comparison.improvements_vs_static:
            lines.append(
                "No improvement or regression was established against the "
                "static baseline; inspect missing metrics and variability."
            )
        lines.append(
            "SLO acceptance thresholds are not set by the benchmark; evaluate "
            "these measurements against the backend's approved SLOs."
        )
        return comparison.model_copy(update={"report": " ".join(lines)})
