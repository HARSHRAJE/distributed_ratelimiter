from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.benchmarking.schemas import (
    BenchmarkRequest,
    BenchmarkResult,
    BenchmarkRun,
)
from app.telemetry.models import BenchmarkResultRecord, BenchmarkRunRecord


class BenchmarkRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def enqueue(
        self,
        request: BenchmarkRequest,
        *,
        git_commit: str,
        k6_script_version: str,
        route_paths: tuple[str, ...],
        now: datetime | None = None,
    ) -> tuple[UUID, list[BenchmarkRunRecord]]:
        created_at = now or datetime.now(timezone.utc)
        batch_id = uuid4()
        strategies = list(request.strategies)
        rotation = batch_id.int % len(strategies)
        strategies = strategies[rotation:] + strategies[:rotation]
        runs = [
            BenchmarkRunRecord(
                id=uuid4(),
                batch_id=batch_id,
                execution_order=order,
                strategy=strategy.value,
                scenario=request.scenario.value,
                service_key=request.service_key,
                environment_id=request.environment_id,
                status="QUEUED",
                config_version=request.strategy_config_versions.get(
                    strategy.value,
                    "UNSPECIFIED",
                ),
                git_commit=git_commit,
                k6_script_version=k6_script_version,
                started_at=None,
                completed_at=None,
                duration_seconds=request.duration_seconds,
                warmup_seconds=request.warmup_seconds,
                tenant_count=request.tenant_count,
                start_rps=request.start_rps,
                peak_rps=request.peak_rps,
                fault_injection_confirmed=request.fault_injection_confirmed,
                slo_thresholds=request.slo_thresholds.model_dump(),
                workload_parameters={
                    "duration_seconds": request.duration_seconds,
                    "warmup_seconds": request.warmup_seconds,
                    "tenant_count": request.tenant_count,
                    "start_rps": request.start_rps,
                    "peak_rps": request.peak_rps,
                    "capacity_profile": (
                        request.capacity_profile.value
                        if request.capacity_profile is not None
                        else None
                    ),
                    "route_paths": list(route_paths),
                },
                error=None,
                created_at=created_at,
            )
            for order, strategy in enumerate(strategies)
        ]
        with self.session.begin():
            self.session.add_all(runs)
            self.session.flush()
        return batch_id, runs

    def claim_next(
        self,
        *,
        now: datetime | None = None,
        stale_after_seconds: int = 5400,
    ) -> BenchmarkRunRecord | None:
        claimed_at = now or datetime.now(timezone.utc)
        with self.session.begin():
            if self.session.get_bind().dialect.name == "postgresql":
                self.session.execute(
                    text("SELECT pg_advisory_xact_lock(819274631902)")
                )
            stale_records = self.session.scalars(
                select(BenchmarkRunRecord)
                .where(
                    BenchmarkRunRecord.status == "RUNNING",
                    BenchmarkRunRecord.started_at
                    < claimed_at - timedelta(seconds=stale_after_seconds),
                )
                .with_for_update(skip_locked=True)
            ).all()
            for stale_record in stale_records:
                stale_record.status = "FAILED"
                stale_record.completed_at = claimed_at
                stale_record.error = "Benchmark worker lease expired"
            active_count = self.session.scalar(
                select(func.count())
                .select_from(BenchmarkRunRecord)
                .where(BenchmarkRunRecord.status == "RUNNING")
            )
            if active_count:
                return None
            query = (
                select(BenchmarkRunRecord)
                .where(BenchmarkRunRecord.status == "QUEUED")
                .order_by(
                    BenchmarkRunRecord.created_at,
                    BenchmarkRunRecord.batch_id,
                    BenchmarkRunRecord.execution_order,
                )
                .limit(1)
                .with_for_update(skip_locked=True)
            )
            record = self.session.scalar(query)
            if record is None:
                return None
            record.status = "RUNNING"
            record.started_at = claimed_at
            record.error = None
            self.session.flush()
            return record

    def complete(
        self,
        run_id: UUID,
        result: BenchmarkResult,
        *,
        now: datetime | None = None,
    ) -> None:
        completed_at = now or datetime.now(timezone.utc)
        with self.session.begin():
            record = self.session.get(BenchmarkRunRecord, run_id)
            if record is None or record.status != "RUNNING":
                raise ValueError("Benchmark run is not in RUNNING state")
            record.status = "COMPLETED"
            record.completed_at = completed_at
            self.session.add(
                BenchmarkResultRecord(
                    id=result.id,
                    run_id=run_id,
                    **result.model_dump(
                        exclude={"id", "run_id", "created_at"}
                    ),
                    created_at=result.created_at,
                )
            )

    def fail(
        self,
        run_id: UUID,
        reason: str,
        *,
        now: datetime | None = None,
    ) -> None:
        with self.session.begin():
            record = self.session.get(BenchmarkRunRecord, run_id)
            if record is None:
                raise ValueError("Benchmark run does not exist")
            if record.status != "RUNNING":
                raise ValueError("Only a running benchmark can fail")
            record.status = "FAILED"
            record.completed_at = now or datetime.now(timezone.utc)
            record.error = reason[:1000]

    def get(self, run_id: UUID) -> BenchmarkRunRecord | None:
        return self.session.get(BenchmarkRunRecord, run_id)

    def result(self, run_id: UUID) -> BenchmarkResultRecord | None:
        return self.session.scalar(
            select(BenchmarkResultRecord).where(
                BenchmarkResultRecord.run_id == run_id
            )
        )

    def history(
        self,
        *,
        service_key: str,
        limit: int,
        scenario: str | None = None,
    ) -> list[BenchmarkRunRecord]:
        query = select(BenchmarkRunRecord).where(
            BenchmarkRunRecord.service_key == service_key
        )
        if scenario is not None:
            query = query.where(BenchmarkRunRecord.scenario == scenario)
        return list(
            self.session.scalars(
                query.order_by(BenchmarkRunRecord.created_at.desc())
                .limit(limit)
            ).all()
        )

    def completed_comparison_runs(
        self,
        *,
        service_key: str,
        scenario: str,
        repeats: int,
    ) -> list[BenchmarkRunRecord]:
        candidates = list(
            self.session.scalars(
                select(BenchmarkRunRecord)
                .where(
                    BenchmarkRunRecord.service_key == service_key,
                    BenchmarkRunRecord.scenario == scenario,
                    BenchmarkRunRecord.status == "COMPLETED",
                )
                .order_by(BenchmarkRunRecord.created_at.desc())
                .limit(1000)
            ).all()
        )
        batch_counts: dict[UUID, int] = {}
        batch_order: list[UUID] = []
        for item in candidates:
            batch_counts[item.batch_id] = batch_counts.get(item.batch_id, 0) + 1
            if item.batch_id not in batch_order:
                batch_order.append(item.batch_id)
        complete_batches = {
            batch_id
            for batch_id in batch_order
            if batch_counts[batch_id] == 3
        }
        selected_batches = set()
        ordered_batches = []
        for item in candidates:
            batch_id = item.batch_id
            if batch_id in complete_batches and batch_id not in selected_batches:
                selected_batches.add(batch_id)
                ordered_batches.append(batch_id)
                if len(ordered_batches) == repeats:
                    break
        selected = set(ordered_batches)
        return [
            item
            for item in candidates
            if item.batch_id in selected
        ]

    def batch_runs(self, batch_id: UUID) -> list[BenchmarkRunRecord]:
        return list(
            self.session.scalars(
                select(BenchmarkRunRecord)
                .where(BenchmarkRunRecord.batch_id == batch_id)
                .order_by(BenchmarkRunRecord.strategy)
            ).all()
        )


def map_result(record: BenchmarkResultRecord) -> BenchmarkResult:
    return BenchmarkResult.model_validate(record)


def map_run(record: BenchmarkRunRecord) -> BenchmarkRun:
    return BenchmarkRun.model_validate(record)
