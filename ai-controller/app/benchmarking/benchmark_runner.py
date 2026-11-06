import logging
from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy.orm import sessionmaker

from app.benchmarking.benchmark_repository import (
    BenchmarkRepository,
    map_run,
)
from app.benchmarking.k6_executor import K6Executor, K6ExecutionError
from app.benchmarking.metrics_collector import BenchmarkMetricsCollector
from app.benchmarking.schemas import BenchmarkResult
from app.config import Settings

LOGGER = logging.getLogger(__name__)


class BenchmarkRunner:
    def __init__(
        self,
        *,
        session_factory: sessionmaker,
        settings: Settings,
        executor: K6Executor | None = None,
        metrics_collector: BenchmarkMetricsCollector | None = None,
    ) -> None:
        self.session_factory = session_factory
        self.settings = settings
        self.executor = executor or K6Executor(
            binary=settings.benchmark_k6_binary,
            target_url=settings.benchmark_target_url,
            allowed_hosts=settings.benchmark_allowed_hosts,
            route_paths=settings.benchmark_route_paths,
            tenant_tokens=settings.benchmark_tenant_tokens,
        )
        self.metrics_collector = metrics_collector or BenchmarkMetricsCollector(
            prometheus_url=settings.prometheus_url,
            timeout_seconds=settings.prometheus_timeout_seconds,
        )

    def claim_next(self):
        with self.session_factory() as session:
            return BenchmarkRepository(session).claim_next(
                stale_after_seconds=(
                    self.settings.benchmark_max_duration_seconds
                    + 600
                    + 180
                )
            )

    async def run_once(self) -> UUID | None:
        record = self.claim_next()
        if record is None:
            return None
        run_id = record.id
        try:
            run = map_run(record)
            if run.peak_rps > self.settings.benchmark_max_rps:
                raise K6ExecutionError(
                    "Queued peak_rps exceeds the benchmark worker's configured "
                    "maximum"
                )
            if len(self.settings.benchmark_tenant_tokens) < run.tenant_count:
                raise K6ExecutionError(
                    "Benchmark worker requires one isolated test tenant JWT "
                    "per configured tenant"
                )
            k6_metrics = await self.executor.execute(run)
            completed_at = datetime.now(timezone.utc)
            with self.session_factory() as session:
                # Reload the persisted run to avoid relying on an ORM instance
                # detached by the claim transaction.
                current = BenchmarkRepository(session).get(run_id)
                if current is None or current.started_at is None:
                    raise RuntimeError("Claimed benchmark run disappeared")
                run = map_run(current).model_copy(
                    update={"completed_at": completed_at}
                )
                collected = await self.metrics_collector.collect(
                    run,
                    k6_metrics,
                    session=session,
                )
            result = BenchmarkResult(
                id=uuid4(),
                run_id=run_id,
                **collected.model_dump(),
                created_at=completed_at,
            )
            with self.session_factory() as session:
                BenchmarkRepository(session).complete(
                    run_id,
                    result,
                    now=completed_at,
                )
        except Exception as error:
            LOGGER.exception("Benchmark run failed: %s", run_id)
            reason = self._safe_error(error)
            with self.session_factory() as session:
                BenchmarkRepository(session).fail(run_id, reason)
        return run_id

    @staticmethod
    def _safe_error(error: Exception) -> str:
        if isinstance(error, K6ExecutionError):
            return str(error)
        if isinstance(error, TypeError):
            return f"Benchmark failed with an invalid result shape: {error}"
        return f"Benchmark failed during execution or metrics collection: {type(error).__name__}"
