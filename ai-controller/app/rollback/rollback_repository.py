from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import Select, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.telemetry.models import PolicyExecutionRecord, PolicyRollbackEventRecord


class RollbackRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def latest_execution(
        self,
        service_key: str,
    ) -> PolicyExecutionRecord | None:
        return self.session.scalar(
            select(PolicyExecutionRecord)
            .where(PolicyExecutionRecord.service_key == service_key)
            .order_by(PolicyExecutionRecord.started_at.desc())
            .limit(1)
        )

    def execution(self, execution_id: UUID) -> PolicyExecutionRecord | None:
        return self.session.get(PolicyExecutionRecord, execution_id)

    def begin(
        self,
        execution: PolicyExecutionRecord,
        *,
        metric: str,
        value: float,
        threshold: float,
        reason: str,
        now: datetime,
    ) -> tuple[PolicyRollbackEventRecord, bool]:
        existing = self.for_execution(execution.id)
        if existing is not None:
            return existing, False
        event = PolicyRollbackEventRecord(
            id=uuid4(),
            execution_id=execution.id,
            service_key=execution.service_key,
            failed_version=execution.resulting_version or execution.previous_version,
            restored_from_version=execution.previous_version,
            rollback_version=None,
            trigger_metric=metric,
            trigger_value=value,
            threshold_value=threshold,
            reason=reason,
            status="DETECTED",
            created_at=now,
            completed_at=None,
            effective_config_verified_at=None,
        )
        execution.status = "ROLLBACK_PENDING"
        self.session.add(event)
        try:
            self.session.commit()
        except IntegrityError:
            self.session.rollback()
            existing = self.for_execution(execution.id)
            if existing is None:
                raise
            return existing, False
        self.session.refresh(event)
        return event, True

    def get(self, rollback_id: UUID) -> PolicyRollbackEventRecord | None:
        return self.session.get(PolicyRollbackEventRecord, rollback_id)

    def for_execution(
        self,
        execution_id: UUID,
    ) -> PolicyRollbackEventRecord | None:
        return self.session.scalar(
            select(PolicyRollbackEventRecord).where(
                PolicyRollbackEventRecord.execution_id == execution_id
            )
        )

    def attempt_count_since(
        self,
        service_key: str,
        since: datetime,
    ) -> int:
        from sqlalchemy import func

        return int(
            self.session.scalar(
                select(func.count(PolicyRollbackEventRecord.id)).where(
                    PolicyRollbackEventRecord.service_key == service_key,
                    PolicyRollbackEventRecord.created_at >= since,
                )
            )
            or 0
        )

    def latest_completed(
        self,
        service_key: str,
    ) -> PolicyRollbackEventRecord | None:
        return self.session.scalar(
            select(PolicyRollbackEventRecord)
            .where(
                PolicyRollbackEventRecord.service_key == service_key,
                PolicyRollbackEventRecord.status == "COMPLETED",
            )
            .order_by(PolicyRollbackEventRecord.completed_at.desc())
            .limit(1)
        )

    def latest_event(
        self,
        service_key: str,
    ) -> PolicyRollbackEventRecord | None:
        return self.session.scalar(
            select(PolicyRollbackEventRecord)
            .where(PolicyRollbackEventRecord.service_key == service_key)
            .order_by(PolicyRollbackEventRecord.created_at.desc())
            .limit(1)
        )

    def history(
        self,
        service_key: str,
        *,
        limit: int,
    ) -> list[PolicyRollbackEventRecord]:
        statement: Select[tuple[PolicyRollbackEventRecord]] = (
            select(PolicyRollbackEventRecord)
            .where(PolicyRollbackEventRecord.service_key == service_key)
            .order_by(PolicyRollbackEventRecord.created_at.desc())
            .limit(limit)
        )
        return list(self.session.scalars(statement).all())

    def update(
        self,
        event: PolicyRollbackEventRecord,
        *,
        status: str,
        rollback_version: int | None = None,
        effective_config_verified_at: datetime | None = None,
        completed_at: datetime | None = None,
        reason: str | None = None,
    ) -> PolicyRollbackEventRecord:
        event.status = status
        if rollback_version is not None:
            event.rollback_version = rollback_version
        if effective_config_verified_at is not None:
            event.effective_config_verified_at = (
                effective_config_verified_at
            )
        if completed_at is not None:
            event.completed_at = completed_at
        if reason is not None:
            event.reason = reason
        self.session.commit()
        self.session.refresh(event)
        return event
