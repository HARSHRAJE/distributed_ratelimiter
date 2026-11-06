from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.chaos.experiment_models import (
    ChaosExperimentRecord,
    ChaosExperimentResultRecord,
)
from app.chaos.schemas import ChaosExperimentRequest


class ChaosExperimentRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def enqueue(
        self,
        request: ChaosExperimentRequest,
        *,
        fault_duration_seconds: int,
        now: datetime | None = None,
    ) -> ChaosExperimentRecord:
        scenario, component = _scenario_details(request.experiment_code.value)
        record = ChaosExperimentRecord(
            id=uuid4(),
            experiment_code=request.experiment_code.value,
            scenario=scenario,
            target_component=component,
            service_key=request.service_key,
            test_environment_id=request.test_environment_id,
            status="QUEUED",
            started_at=None,
            completed_at=None,
            created_at=now or datetime.now(timezone.utc),
            fault_duration_seconds=fault_duration_seconds,
            operator_note=request.operator_note,
            error=None,
        )
        with self.session.begin():
            self.session.add(record)
            self.session.flush()
        return record

    def claim_next(
        self,
        *,
        now: datetime | None = None,
        lease_seconds: int = 180,
    ) -> ChaosExperimentRecord | None:
        claimed_at = now or datetime.now(timezone.utc)
        with self.session.begin():
            if self.session.get_bind().dialect.name == "postgresql":
                self.session.execute(
                    text("SELECT pg_advisory_xact_lock(82734190217)")
                )
            stale = self.session.scalars(
                select(ChaosExperimentRecord)
                .where(
                    ChaosExperimentRecord.status == "RUNNING",
                    ChaosExperimentRecord.started_at
                    < claimed_at - timedelta(seconds=lease_seconds),
                )
                .with_for_update(skip_locked=True)
            ).all()
            for record in stale:
                record.status = "FAILED"
                record.completed_at = claimed_at
                record.error = (
                    "Chaos worker lease expired; fault recovery must be "
                    "verified manually before another experiment"
                )
            active = self.session.scalar(
                select(func.count())
                .select_from(ChaosExperimentRecord)
                .where(ChaosExperimentRecord.status == "RUNNING")
            )
            if active:
                return None
            record = self.session.scalar(
                select(ChaosExperimentRecord)
                .where(ChaosExperimentRecord.status == "QUEUED")
                .order_by(
                    ChaosExperimentRecord.created_at,
                    ChaosExperimentRecord.id,
                )
                .limit(1)
                .with_for_update(skip_locked=True)
            )
            if record is None:
                return None
            record.status = "RUNNING"
            record.started_at = claimed_at
            self.session.flush()
            return record

    def complete(
        self,
        experiment_id: UUID,
        *,
        result: dict,
        now: datetime | None = None,
    ) -> None:
        completed_at = now or datetime.now(timezone.utc)
        with self.session.begin():
            record = self.session.get(ChaosExperimentRecord, experiment_id)
            if record is None or record.status != "RUNNING":
                raise ValueError("Chaos experiment is not RUNNING")
            record.status = "COMPLETED"
            record.completed_at = completed_at
            self.session.add(
                ChaosExperimentResultRecord(
                    id=uuid4(),
                    experiment_id=experiment_id,
                    requests_sent=result["requests_sent"],
                    accepted_requests=result["accepted_requests"],
                    rejected_requests=result["rejected_requests"],
                    backend_errors=result["backend_errors"],
                    gateway_errors=result["gateway_errors"],
                    policy_consistency=result["policy_consistency"],
                    recovery_success=result["recovery_success"],
                    recovery_time_ms=result["recovery_time_ms"],
                    safety_violations=result["safety_violations"],
                    details=result["details"],
                    created_at=completed_at,
                )
            )

    def fail(
        self,
        experiment_id: UUID,
        reason: str,
        *,
        now: datetime | None = None,
    ) -> None:
        with self.session.begin():
            record = self.session.get(ChaosExperimentRecord, experiment_id)
            if record is None or record.status != "RUNNING":
                raise ValueError("Only a running chaos experiment can fail")
            record.status = "FAILED"
            record.completed_at = now or datetime.now(timezone.utc)
            record.error = reason[:2000]

    def get(self, experiment_id: UUID) -> ChaosExperimentRecord | None:
        return self.session.get(ChaosExperimentRecord, experiment_id)

    def result(
        self,
        experiment_id: UUID,
    ) -> ChaosExperimentResultRecord | None:
        return self.session.scalar(
            select(ChaosExperimentResultRecord).where(
                ChaosExperimentResultRecord.experiment_id == experiment_id
            )
        )

    def history(
        self,
        *,
        test_environment_id: str,
        service_key: str | None,
        limit: int,
    ) -> list[ChaosExperimentRecord]:
        query = select(ChaosExperimentRecord).where(
            ChaosExperimentRecord.test_environment_id == test_environment_id
        )
        if service_key is not None:
            query = query.where(
                ChaosExperimentRecord.service_key == service_key
            )
        return list(
            self.session.scalars(
                query.order_by(ChaosExperimentRecord.created_at.desc())
                .limit(limit)
            ).all()
        )


def _scenario_details(code: str) -> tuple[str, str]:
    from app.chaos.schemas import (
        ChaosExperimentCode,
        SCENARIO_DETAILS,
    )

    return SCENARIO_DETAILS[ChaosExperimentCode(code)]
