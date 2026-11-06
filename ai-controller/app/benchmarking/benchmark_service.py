from uuid import UUID

from app.benchmarking.benchmark_repository import BenchmarkRepository
from app.benchmarking.comparison_engine import ComparisonEngine
from app.benchmarking.report_generator import ReportGenerator
from app.benchmarking.schemas import (
    BenchmarkScenario,
    BenchmarkComparison,
    BenchmarkRequest,
    BenchmarkRunDetails,
    BenchmarkStrategy,
    BenchmarkSubmission,
)
from app.benchmarking.k6_executor import K6_SCRIPT_VERSION
from app.benchmarking.benchmark_repository import map_result, map_run
from app.config import Settings
from sqlalchemy.orm import Session


class BenchmarkService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def submit(
        self,
        request: BenchmarkRequest,
        *,
        session: Session,
    ) -> BenchmarkSubmission:
        if request.service_key not in self.settings.service_keys:
            raise ValueError("Service is not configured for benchmarking")
        if self.settings.benchmark_git_commit == "UNSPECIFIED":
            raise ValueError(
                "AI_CONTROLLER_GIT_COMMIT must identify the tested source revision"
            )
        if request.duration_seconds > self.settings.benchmark_max_duration_seconds:
            raise ValueError("Benchmark duration exceeds the configured maximum")
        if request.peak_rps > self.settings.benchmark_max_rps:
            raise ValueError(
                "peak_rps exceeds the configured gradual-load maximum of "
                f"{self.settings.benchmark_max_rps}"
            )
        if request.tenant_count > max(20, request.peak_rps):
            raise ValueError(
                "tenant_count cannot exceed the k6 preallocated VU limit; "
                "raise peak_rps or reduce tenant_count"
            )
        repository = BenchmarkRepository(session)
        batch_id, runs = repository.enqueue(
            request,
            git_commit=self.settings.benchmark_git_commit,
            k6_script_version=K6_SCRIPT_VERSION,
            route_paths=self.settings.benchmark_route_paths,
        )
        return BenchmarkSubmission(
            batch_id=batch_id,
            run_ids=[record.id for record in runs],
            status="QUEUED",
        )

    @staticmethod
    def details(
        run_id: UUID,
        *,
        session: Session,
    ) -> BenchmarkRunDetails | None:
        repository = BenchmarkRepository(session)
        run = repository.get(run_id)
        if run is None:
            return None
        result = repository.result(run_id)
        return BenchmarkRunDetails(
            run=map_run(run),
            result=map_result(result) if result is not None else None,
        )

    def compare(
        self,
        *,
        service_key: str,
        scenario: BenchmarkScenario,
        limit: int,
        batch_id: UUID | None,
        session: Session,
    ) -> BenchmarkComparison:
        repository = BenchmarkRepository(session)
        if batch_id is None:
            runs = repository.completed_comparison_runs(
                service_key=service_key,
                scenario=scenario.value,
                repeats=limit,
            )
        else:
            runs = repository.batch_runs(batch_id)
            runs = [
                item for item in runs
                if item.service_key == service_key
                and item.scenario == scenario.value
                and item.status == "COMPLETED"
            ]
            if len(runs) != 3:
                raise ValueError(
                    "A batch can be compared only after all three strategies "
                    "have completed"
                )
        completed_runs = [item for item in runs if item.status == "COMPLETED"]
        rows = [
            (map_run(item), repository.result(item.id))
            for item in completed_runs
        ]
        rows = [
            (run, map_result(result))
            for run, result in rows
            if result is not None
        ]
        if rows and {run.strategy for run, _ in rows} != set(BenchmarkStrategy):
            raise ValueError(
                "A comparison requires completed measurements for all three "
                "strategies"
            )
        environment_ids = {run.environment_id for run, _ in rows}
        if len(environment_ids) > 1:
            raise ValueError(
                "Benchmarks from different environment identifiers cannot "
                "be compared"
            )
        comparisons = ComparisonEngine().compare(
            service_key=service_key,
            scenario=scenario,
            runs=rows,
            environment_id=next(iter(environment_ids), None),
        )
        return ReportGenerator().generate(comparisons)
