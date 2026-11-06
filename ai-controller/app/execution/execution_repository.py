from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import Select, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.telemetry.models import (
    ExecutionGlobalControlRecord,
    ExecutionServiceControlRecord,
    PolicyExecutionRecord,
)


ACTIVE_STATUSES = (
    "PENDING",
    "VALIDATING",
    "SUBMITTED",
    "ROLLBACK_PENDING",
)


class ExecutionRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def begin(
        self,
        *,
        recommendation_id: UUID,
        service_key: str,
        previous_version: int,
        previous_rate: float,
        proposed_rate: float,
        started_at: datetime,
    ) -> tuple[PolicyExecutionRecord, bool]:
        existing = self.active_for_service(service_key)
        if existing is not None:
            return existing, False
        record = PolicyExecutionRecord(
            id=uuid4(),
            recommendation_id=recommendation_id,
            service_key=service_key,
            policy_id=None,
            previous_version=previous_version,
            resulting_version=None,
            previous_rate=previous_rate,
            proposed_rate=proposed_rate,
            status="PENDING",
            failure_reason=None,
            started_at=started_at,
            completed_at=None,
        )
        self.session.add(record)
        try:
            self.session.commit()
        except IntegrityError:
            self.session.rollback()
            existing = self.active_for_service(service_key)
            if existing is None:
                raise
            return existing, False
        self.session.refresh(record)
        return record, True

    def get(self, execution_id: UUID) -> PolicyExecutionRecord | None:
        return self.session.get(PolicyExecutionRecord, execution_id)

    def active_for_service(
        self,
        service_key: str,
    ) -> PolicyExecutionRecord | None:
        return self.session.scalar(
            select(PolicyExecutionRecord)
            .where(
                PolicyExecutionRecord.service_key == service_key,
                PolicyExecutionRecord.status.in_(ACTIVE_STATUSES),
            )
            .order_by(PolicyExecutionRecord.started_at.desc())
            .limit(1)
        )

    def pause_service(
        self,
        service_key: str,
        *,
        reason: str,
        now: datetime,
    ) -> ExecutionServiceControlRecord | None:
        control = self.control(service_key)
        if control is None:
            return None
        control.enabled = False
        control.paused_reason = reason[:1000]
        control.updated_at = now
        self.session.commit()
        self.session.refresh(control)
        return control

    def global_kill_switch_active(self) -> bool:
        control = self.session.get(ExecutionGlobalControlRecord, "global")
        return control is not None and control.kill_switch_active

    def set_global_kill_switch(
        self,
        *,
        active: bool,
        now: datetime,
    ) -> ExecutionGlobalControlRecord:
        control = self.session.get(ExecutionGlobalControlRecord, "global")
        if control is None:
            control = ExecutionGlobalControlRecord(
                id="global",
                kill_switch_active=active,
                updated_at=now,
            )
        else:
            control.kill_switch_active = active
            control.updated_at = now
        if active:
            service_controls = self.session.scalars(
                select(ExecutionServiceControlRecord)
            ).all()
            for service_control in service_controls:
                service_control.enabled = False
                service_control.paused_reason = (
                    "Global emergency kill switch is active"
                )
                service_control.updated_at = now
        self.session.add(control)
        self.session.commit()
        self.session.refresh(control)
        return control

    def latest_for_recommendation(
        self,
        recommendation_id: UUID,
    ) -> PolicyExecutionRecord | None:
        return self.session.scalar(
            select(PolicyExecutionRecord)
            .where(
                PolicyExecutionRecord.recommendation_id == recommendation_id
            )
            .order_by(PolicyExecutionRecord.started_at.desc())
            .limit(1)
        )

    def latest(self, service_key: str) -> PolicyExecutionRecord | None:
        return self.session.scalar(
            select(PolicyExecutionRecord)
            .where(PolicyExecutionRecord.service_key == service_key)
            .order_by(PolicyExecutionRecord.started_at.desc())
            .limit(1)
        )

    def history(
        self,
        service_key: str,
        *,
        limit: int,
    ) -> list[PolicyExecutionRecord]:
        statement: Select[tuple[PolicyExecutionRecord]] = (
            select(PolicyExecutionRecord)
            .where(PolicyExecutionRecord.service_key == service_key)
            .order_by(PolicyExecutionRecord.started_at.desc())
            .limit(limit)
        )
        return list(self.session.scalars(statement).all())

    def recent_changes(self, service_key: str, *, since: datetime) -> int:
        from sqlalchemy import func

        return int(
            self.session.scalar(
                select(func.count(PolicyExecutionRecord.id)).where(
                    PolicyExecutionRecord.service_key == service_key,
                    PolicyExecutionRecord.started_at >= since,
                    PolicyExecutionRecord.status.in_(
                        ("SUBMITTED", "APPLIED")
                    ),
                )
            )
            or 0
        )

    def last_change_at(self, service_key: str) -> datetime | None:
        return self.session.scalar(
            select(PolicyExecutionRecord.started_at)
            .where(
                PolicyExecutionRecord.service_key == service_key,
                PolicyExecutionRecord.status.in_(
                    ("SUBMITTED", "APPLIED")
                ),
            )
            .order_by(PolicyExecutionRecord.started_at.desc())
            .limit(1)
        )

    def update(
        self,
        record: PolicyExecutionRecord,
        *,
        status: str,
        resulting_version: int | None = None,
        effective_config_verified_at: datetime | None = None,
        policy_submitted_at: datetime | None = None,
        failure_reason: str | None = None,
        completed_at: datetime | None = None,
    ) -> PolicyExecutionRecord:
        record.status = status
        if resulting_version is not None:
            record.resulting_version = resulting_version
        if effective_config_verified_at is not None:
            record.effective_config_verified_at = (
                effective_config_verified_at
            )
        if policy_submitted_at is not None:
            record.policy_submitted_at = policy_submitted_at
        record.failure_reason = failure_reason
        record.completed_at = completed_at
        self.session.commit()
        self.session.refresh(record)
        return record

    def control(
        self,
        service_key: str,
    ) -> ExecutionServiceControlRecord | None:
        return self.session.get(ExecutionServiceControlRecord, service_key)

    def save_control(
        self,
        control: ExecutionServiceControlRecord,
    ) -> ExecutionServiceControlRecord:
        self.session.add(control)
        self.session.commit()
        self.session.refresh(control)
        return control
