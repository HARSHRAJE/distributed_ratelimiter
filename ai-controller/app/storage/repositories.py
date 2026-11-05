from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import Select, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from app.telemetry.aggregator import TelemetryAggregator
from app.telemetry.collector import CollectedTelemetry
from app.telemetry.models import (
    CollectionStatusRecord,
    TelemetrySampleRecord,
    TelemetryWindowRecord,
)


class TelemetryRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def save_sample(self, sample: CollectedTelemetry) -> bool:
        values = {
            "id": sample.id,
            "service_key": sample.service_key,
            "window_start": sample.timestamp,
            "window_seconds": sample.window_seconds,
            "incoming_rps": sample.incoming_rps,
            "allowed_rps": sample.allowed_rps,
            "rejected_rps": sample.rejected_rps,
            "p95_latency_ms": sample.p95_latency_ms,
            "p99_latency_ms": sample.p99_latency_ms,
            "error_rate": sample.error_rate,
            "cpu_utilization": sample.cpu_utilization,
            "memory_utilization": sample.memory_utilization,
            "redis_latency_ms": sample.redis_latency_ms,
            "queue_depth": sample.queue_depth,
            "data_quality": sample.data_quality,
            "collected_at": sample.collected_at,
        }
        statement = self._insert(TelemetrySampleRecord, values)
        statement = statement.on_conflict_do_nothing(
            index_elements=[
                TelemetrySampleRecord.service_key,
                TelemetrySampleRecord.window_start,
                TelemetrySampleRecord.window_seconds,
            ]
        ).returning(TelemetrySampleRecord.id)
        inserted = self.session.execute(statement).scalar_one_or_none()
        self.session.commit()
        return inserted is not None

    def aggregate_window(
        self,
        service_key: str,
        *,
        window_start: datetime,
        window_seconds: int,
        collection_interval_seconds: int,
        aggregator: TelemetryAggregator,
    ) -> None:
        start = window_start - timedelta(seconds=window_seconds)
        rows = self.session.scalars(
            select(TelemetrySampleRecord)
            .where(
                TelemetrySampleRecord.service_key == service_key,
                TelemetrySampleRecord.window_start > start,
                TelemetrySampleRecord.window_start <= window_start,
            )
            .order_by(TelemetrySampleRecord.window_start)
        ).all()
        values = aggregator.aggregate(
            service_key,
            rows,
            window_start=window_start,
            window_seconds=window_seconds,
            collection_interval_seconds=collection_interval_seconds,
        )
        values["created_at"] = datetime.now(timezone.utc)
        statement = self._insert(TelemetryWindowRecord, values)
        statement = statement.on_conflict_do_update(
            index_elements=[
                TelemetryWindowRecord.service_key,
                TelemetryWindowRecord.window_start,
                TelemetryWindowRecord.window_seconds,
            ],
            set_={
                key: value
                for key, value in values.items()
                if key not in {"service_key", "window_start", "window_seconds"}
            },
        )
        self.session.execute(statement)
        self.session.commit()

    def latest(self, service_key: str) -> TelemetrySampleRecord | None:
        statement: Select[tuple[TelemetrySampleRecord]] = (
            select(TelemetrySampleRecord)
            .where(TelemetrySampleRecord.service_key == service_key)
            .order_by(TelemetrySampleRecord.window_start.desc())
            .limit(1)
        )
        return self.session.scalar(statement)

    def history(
        self,
        service_key: str,
        *,
        limit: int,
        before: datetime | None = None,
    ) -> list[TelemetrySampleRecord]:
        statement = select(TelemetrySampleRecord).where(
            TelemetrySampleRecord.service_key == service_key
        )
        if before is not None:
            statement = statement.where(
                TelemetrySampleRecord.window_start < before
            )
        return list(
            self.session.scalars(
                statement.order_by(
                    TelemetrySampleRecord.window_start.desc()
                ).limit(limit)
            ).all()
        )

    def collection_status(self) -> list[CollectionStatusRecord]:
        return list(
            self.session.scalars(
                select(CollectionStatusRecord).order_by(
                    CollectionStatusRecord.service_key
                )
            ).all()
        )

    def record_collection_success(
        self,
        service_key: str,
        *,
        attempted_at: datetime,
        quality: str,
    ) -> None:
        values = {
            "service_key": service_key,
            "state": "success",
            "last_attempt_at": attempted_at,
            "last_success_at": attempted_at,
            "last_quality": quality,
            "last_error": None,
            "updated_at": datetime.now(timezone.utc),
        }
        statement = self._insert(CollectionStatusRecord, values)
        statement = statement.on_conflict_do_update(
            index_elements=[CollectionStatusRecord.service_key],
            set_={key: value for key, value in values.items() if key != "service_key"},
        )
        self.session.execute(statement)
        self.session.commit()

    def record_collection_failure(
        self,
        service_key: str,
        *,
        attempted_at: datetime,
        error_type: str,
    ) -> None:
        existing = self.session.get(CollectionStatusRecord, service_key)
        values = {
            "service_key": service_key,
            "state": "failed",
            "last_attempt_at": attempted_at,
            "last_success_at": (
                existing.last_success_at if existing is not None else None
            ),
            "last_quality": (
                existing.last_quality if existing is not None else None
            ),
            "last_error": error_type[:100],
            "updated_at": datetime.now(timezone.utc),
        }
        statement = self._insert(CollectionStatusRecord, values)
        statement = statement.on_conflict_do_update(
            index_elements=[CollectionStatusRecord.service_key],
            set_={key: value for key, value in values.items() if key != "service_key"},
        )
        self.session.execute(statement)
        self.session.commit()

    def _insert(self, model: type[Any], values: dict[str, Any]) -> Any:
        dialect = self.session.get_bind().dialect.name
        if dialect == "postgresql":
            return pg_insert(model).values(**values)
        if dialect == "sqlite":
            return sqlite_insert(model).values(**values)
        raise RuntimeError(
            f"Unsupported database dialect for telemetry writes: {dialect}"
        )
