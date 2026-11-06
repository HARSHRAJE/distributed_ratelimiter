from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.telemetry.models import Base


class ChaosExperimentRecord(Base):
    __tablename__ = "chaos_experiments"
    __table_args__ = (
        Index(
            "idx_chaos_experiments_status_created",
            "status",
            "created_at",
        ),
        Index(
            "idx_chaos_experiments_env_service_created",
            "test_environment_id",
            "service_key",
            "created_at",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    experiment_code: Mapped[str] = mapped_column(String(50), nullable=False)
    scenario: Mapped[str] = mapped_column(String(100), nullable=False)
    target_component: Mapped[str] = mapped_column(String(100), nullable=False)
    service_key: Mapped[str] = mapped_column(String(100), nullable=False)
    test_environment_id: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    fault_duration_seconds: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )
    operator_note: Mapped[str] = mapped_column(Text, nullable=False)
    error: Mapped[str | None] = mapped_column(Text)


class ChaosExperimentResultRecord(Base):
    __tablename__ = "chaos_experiment_results"
    __table_args__ = (
        UniqueConstraint(
            "experiment_id",
            name="uq_chaos_experiment_result_experiment",
        ),
        Index(
            "idx_chaos_experiment_results_created",
            "created_at",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    experiment_id: Mapped[UUID] = mapped_column(
        ForeignKey("chaos_experiments.id"),
        nullable=False,
    )
    requests_sent: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        default=0,
    )
    accepted_requests: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        default=0,
    )
    rejected_requests: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        default=0,
    )
    backend_errors: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        default=0,
    )
    gateway_errors: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        default=0,
    )
    policy_consistency: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
    )
    recovery_success: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
    )
    recovery_time_ms: Mapped[int | None] = mapped_column(BigInteger)
    safety_violations: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        default=0,
    )
    details: Mapped[dict] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
