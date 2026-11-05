from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    DateTime,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class TelemetrySampleRecord(Base):
    __tablename__ = "telemetry_samples"
    __table_args__ = (
        UniqueConstraint(
            "service_key",
            "window_start",
            "window_seconds",
            name="uq_telemetry_sample_window",
        ),
        Index(
            "idx_telemetry_service_time",
            "service_key",
            "window_start",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    service_key: Mapped[str] = mapped_column(String(100), nullable=False)
    window_start: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    window_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    incoming_rps: Mapped[float | None] = mapped_column(Numeric(14, 3))
    allowed_rps: Mapped[float | None] = mapped_column(Numeric(14, 3))
    rejected_rps: Mapped[float | None] = mapped_column(Numeric(14, 3))
    p95_latency_ms: Mapped[float | None] = mapped_column(Numeric(14, 3))
    p99_latency_ms: Mapped[float | None] = mapped_column(Numeric(14, 3))
    error_rate: Mapped[float | None] = mapped_column(Numeric(10, 6))
    cpu_utilization: Mapped[float | None] = mapped_column(Numeric(7, 3))
    memory_utilization: Mapped[float | None] = mapped_column(Numeric(7, 3))
    redis_latency_ms: Mapped[float | None] = mapped_column(Numeric(14, 3))
    queue_depth: Mapped[float | None] = mapped_column(Numeric(14, 3))
    data_quality: Mapped[str] = mapped_column(String(20), nullable=False)
    collected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )


class TelemetryWindowRecord(Base):
    __tablename__ = "telemetry_windows"
    __table_args__ = (
        UniqueConstraint(
            "service_key",
            "window_start",
            "window_seconds",
            name="uq_telemetry_aggregate_window",
        ),
        Index(
            "idx_telemetry_window_service_time",
            "service_key",
            "window_start",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    service_key: Mapped[str] = mapped_column(String(100), nullable=False)
    window_start: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    window_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    mean_incoming_rps: Mapped[float | None] = mapped_column(Numeric(14, 3))
    max_incoming_rps: Mapped[float | None] = mapped_column(Numeric(14, 3))
    mean_allowed_rps: Mapped[float | None] = mapped_column(Numeric(14, 3))
    mean_rejected_rps: Mapped[float | None] = mapped_column(Numeric(14, 3))
    mean_p95_latency_ms: Mapped[float | None] = mapped_column(Numeric(14, 3))
    max_p95_latency_ms: Mapped[float | None] = mapped_column(Numeric(14, 3))
    mean_p99_latency_ms: Mapped[float | None] = mapped_column(Numeric(14, 3))
    max_p99_latency_ms: Mapped[float | None] = mapped_column(Numeric(14, 3))
    mean_error_rate: Mapped[float | None] = mapped_column(Numeric(10, 6))
    missing_sample_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )


class CollectionStatusRecord(Base):
    __tablename__ = "telemetry_collection_status"

    service_key: Mapped[str] = mapped_column(
        String(100),
        primary_key=True,
    )
    state: Mapped[str] = mapped_column(String(20), nullable=False)
    last_attempt_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    last_success_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    last_quality: Mapped[str | None] = mapped_column(String(20))
    last_error: Mapped[str | None] = mapped_column(String(100))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
