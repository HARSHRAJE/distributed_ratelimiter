from datetime import datetime
from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from app.telemetry.models import TelemetrySampleRecord


class HealthMonitor:
    def __init__(self, session: Session) -> None:
        self.session = session

    def windows_since(
        self,
        service_key: str,
        since: datetime,
        *,
        limit: int = 100,
    ) -> list[TelemetrySampleRecord]:
        statement: Select[tuple[TelemetrySampleRecord]] = (
            select(TelemetrySampleRecord)
            .where(
                TelemetrySampleRecord.service_key == service_key,
                TelemetrySampleRecord.window_start >= since,
            )
            .order_by(TelemetrySampleRecord.window_start.desc())
            .limit(limit)
        )
        return list(reversed(self.session.scalars(statement).all()))

    def latest_before(
        self,
        service_key: str,
        before: datetime,
    ) -> TelemetrySampleRecord | None:
        return self.session.scalar(
            select(TelemetrySampleRecord)
            .where(
                TelemetrySampleRecord.service_key == service_key,
                TelemetrySampleRecord.window_start < before,
            )
            .order_by(TelemetrySampleRecord.window_start.desc())
            .limit(1)
        )
