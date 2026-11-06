from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    BigInteger,
    Integer,
    JSON,
    Numeric,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import INET
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class SecurityAuditEventRecord(Base):
    __tablename__ = "security_audit_events"
    __table_args__ = (
        Index(
            "idx_security_audit_tenant",
            "tenant_id",
            "created_at",
        ),
        Index(
            "idx_security_audit_type",
            "event_type",
            "created_at",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    actor_id: Mapped[str | None] = mapped_column(String(128))
    tenant_id: Mapped[str | None] = mapped_column(String(128))
    service_key: Mapped[str | None] = mapped_column(String(100))
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    resource_id: Mapped[str | None] = mapped_column(String(128))
    outcome: Mapped[str] = mapped_column(String(30), nullable=False)
    source_ip: Mapped[str | None] = mapped_column(
        String(45).with_variant(INET(), "postgresql")
    )
    details: Mapped[dict | None] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )


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


class TrafficForecastRecord(Base):
    __tablename__ = "traffic_forecasts"
    __table_args__ = (
        UniqueConstraint(
            "service_key",
            "target_timestamp",
            "model_name",
            "horizon_seconds",
            name="uq_traffic_forecast_target_model_horizon",
        ),
        Index(
            "idx_forecasts_service_time",
            "service_key",
            "target_timestamp",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    service_key: Mapped[str] = mapped_column(String(100), nullable=False)
    forecast_generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    target_timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    horizon_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    predicted_rps: Mapped[float] = mapped_column(Numeric(14, 3), nullable=False)
    model_name: Mapped[str] = mapped_column(String(100), nullable=False)
    model_version: Mapped[str] = mapped_column(String(50), nullable=False)
    lower_bound: Mapped[float | None] = mapped_column(Numeric(14, 3))
    upper_bound: Mapped[float | None] = mapped_column(Numeric(14, 3))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )


class PolicyRecommendationRecord(Base):
    __tablename__ = "policy_recommendations"
    __table_args__ = (
        Index(
            "idx_recommendations_service_generated",
            "service_key",
            "generated_at",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    service_key: Mapped[str] = mapped_column(String(100), nullable=False)
    scope: Mapped[str] = mapped_column(String(20), nullable=False)
    current_rate: Mapped[float] = mapped_column(Numeric(14, 3), nullable=False)
    recommended_rate: Mapped[float] = mapped_column(
        Numeric(14, 3),
        nullable=False,
    )
    action: Mapped[str] = mapped_column(String(20), nullable=False)
    reason: Mapped[str] = mapped_column(String, nullable=False)
    forecast_rps: Mapped[float] = mapped_column(Numeric(14, 3), nullable=False)
    forecast_confidence: Mapped[float] = mapped_column(
        Numeric(6, 5),
        nullable=False,
    )
    safe_capacity_rps: Mapped[float] = mapped_column(
        Numeric(14, 3),
        nullable=False,
    )
    policy_version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )


class RecommendationValidationRecord(Base):
    __tablename__ = "recommendation_validations"
    __table_args__ = (
        Index(
            "idx_recommendation_validations_recommendation_time",
            "recommendation_id",
            "validated_at",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    recommendation_id: Mapped[UUID] = mapped_column(
        ForeignKey("policy_recommendations.id"),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    validation_result: Mapped[dict] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"),
        nullable=False,
    )
    validated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    validator_version: Mapped[str] = mapped_column(String(20), nullable=False)


class ShadowEvaluationRecord(Base):
    __tablename__ = "shadow_evaluations"
    __table_args__ = (
        Index(
            "idx_shadow_evaluations_service_created",
            "service_key",
            "created_at",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    recommendation_id: Mapped[UUID] = mapped_column(
        ForeignKey("policy_recommendations.id"),
        nullable=False,
    )
    service_key: Mapped[str] = mapped_column(String(100), nullable=False)
    current_policy_version: Mapped[int] = mapped_column(Integer, nullable=False)
    current_rate: Mapped[float] = mapped_column(Numeric(14, 3), nullable=False)
    proposed_rate: Mapped[float] = mapped_column(Numeric(14, 3), nullable=False)
    actual_incoming_rps: Mapped[float] = mapped_column(
        Numeric(14, 3),
        nullable=False,
    )
    estimated_admitted_rps: Mapped[float] = mapped_column(
        Numeric(14, 3),
        nullable=False,
    )
    estimated_rejected_rps: Mapped[float] = mapped_column(
        Numeric(14, 3),
        nullable=False,
    )
    evaluation_window_seconds: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )
    evaluation_result: Mapped[dict] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )


class PolicyExecutionRecord(Base):
    __tablename__ = "policy_executions"
    __table_args__ = (
        Index(
            "idx_policy_executions_service_started",
            "service_key",
            "started_at",
        ),
        Index(
            "uq_policy_executions_active_service",
            "service_key",
            unique=True,
            sqlite_where=text(
                "status IN ('PENDING', 'VALIDATING', 'SUBMITTED', "
                "'ROLLBACK_PENDING')"
            ),
            postgresql_where=text(
                "status IN ('PENDING', 'VALIDATING', 'SUBMITTED', "
                "'ROLLBACK_PENDING')"
            ),
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    recommendation_id: Mapped[UUID] = mapped_column(
        ForeignKey("policy_recommendations.id"),
        nullable=False,
        index=True,
    )
    service_key: Mapped[str] = mapped_column(String(100), nullable=False)
    policy_id: Mapped[UUID | None] = mapped_column()
    previous_version: Mapped[int] = mapped_column(Integer, nullable=False)
    resulting_version: Mapped[int | None] = mapped_column(Integer)
    effective_config_verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    policy_submitted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    previous_rate: Mapped[float] = mapped_column(Numeric(14, 3), nullable=False)
    proposed_rate: Mapped[float] = mapped_column(Numeric(14, 3), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    failure_reason: Mapped[str | None] = mapped_column(String)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )


class ExecutionServiceControlRecord(Base):
    __tablename__ = "execution_service_controls"

    service_key: Mapped[str] = mapped_column(
        String(100),
        primary_key=True,
    )
    enabled: Mapped[bool] = mapped_column(nullable=False, default=False)
    manual_override: Mapped[bool] = mapped_column(nullable=False, default=False)
    rollout_started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    paused_reason: Mapped[str | None] = mapped_column(String)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )


class ExecutionGlobalControlRecord(Base):
    __tablename__ = "execution_global_controls"

    id: Mapped[str] = mapped_column(String(20), primary_key=True)
    kill_switch_active: Mapped[bool] = mapped_column(nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )


class PolicyRollbackEventRecord(Base):
    __tablename__ = "policy_rollback_events"
    __table_args__ = (
        Index(
            "uq_policy_rollback_events_execution",
            "execution_id",
            unique=True,
        ),
        Index(
            "idx_policy_rollback_events_service_created",
            "service_key",
            "created_at",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    execution_id: Mapped[UUID] = mapped_column(
        ForeignKey("policy_executions.id"),
        nullable=False,
    )
    service_key: Mapped[str] = mapped_column(String(100), nullable=False)
    failed_version: Mapped[int] = mapped_column(Integer, nullable=False)
    restored_from_version: Mapped[int] = mapped_column(Integer, nullable=False)
    rollback_version: Mapped[int | None] = mapped_column(Integer)
    trigger_metric: Mapped[str] = mapped_column(String(50), nullable=False)
    trigger_value: Mapped[float] = mapped_column(Numeric(14, 3), nullable=False)
    threshold_value: Mapped[float] = mapped_column(Numeric(14, 3), nullable=False)
    reason: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    effective_config_verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )


class AdaptiveControlBreakerRecord(Base):
    __tablename__ = "adaptive_control_breakers"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    service_key: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False)
    failure_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    success_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    half_open_attempts: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
    )
    opened_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_attempt_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    last_failure_reason: Mapped[str | None] = mapped_column(String)
    manual_disabled: Mapped[bool] = mapped_column(nullable=False, default=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )


class CircuitBreakerEventRecord(Base):
    __tablename__ = "circuit_breaker_events"
    __table_args__ = (
        Index(
            "idx_circuit_breaker_events_service_created",
            "service_key",
            "created_at",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    service_key: Mapped[str] = mapped_column(String(100), nullable=False)
    from_state: Mapped[str] = mapped_column(String(16), nullable=False)
    to_state: Mapped[str] = mapped_column(String(16), nullable=False)
    reason: Mapped[str] = mapped_column(String, nullable=False)
    actor: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )


class ComponentHealthBreakerRecord(Base):
    __tablename__ = "component_health_breakers"
    __table_args__ = (
        UniqueConstraint("service_key", "component", name="uq_component_health_service"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    service_key: Mapped[str] = mapped_column(String(100), nullable=False)
    component: Mapped[str] = mapped_column(String(32), nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False)
    failure_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_failure_reason: Mapped[str | None] = mapped_column(String)
    next_attempt_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )


class AdaptiveExecutionReservationRecord(Base):
    __tablename__ = "adaptive_execution_reservations"
    __table_args__ = (
        UniqueConstraint(
            "service_key",
            "recommendation_id",
            name="uq_adaptive_reservation_recommendation",
        ),
        Index(
            "idx_adaptive_reservations_service_active",
            "service_key",
            "active",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    service_key: Mapped[str] = mapped_column(String(100), nullable=False)
    recommendation_id: Mapped[UUID] = mapped_column(
        ForeignKey("policy_recommendations.id"),
        nullable=False,
    )
    active: Mapped[bool] = mapped_column(nullable=False, default=True)
    recovery_check: Mapped[bool] = mapped_column(nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class TenantAllocationConfigRecord(Base):
    __tablename__ = "tenant_allocation_configs"
    __table_args__ = (
        UniqueConstraint(
            "service_key",
            "tenant_id",
            name="uq_tenant_allocation_config_service_tenant",
        ),
        Index(
            "idx_tenant_allocation_configs_service",
            "service_key",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    service_key: Mapped[str] = mapped_column(String(100), nullable=False)
    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    weight: Mapped[float] = mapped_column(Numeric(14, 3), nullable=False)
    minimum_rate: Mapped[float] = mapped_column(Numeric(14, 3), nullable=False)
    maximum_rate: Mapped[float] = mapped_column(Numeric(14, 3), nullable=False)
    adaptive_enabled: Mapped[bool] = mapped_column(nullable=False, default=True)
    predicted_demand: Mapped[float] = mapped_column(
        Numeric(14, 3),
        nullable=False,
        default=0,
    )
    current_allocation: Mapped[float] = mapped_column(
        Numeric(14, 3),
        nullable=False,
        default=0,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )


class TenantAllocationRunRecord(Base):
    __tablename__ = "tenant_allocation_runs"
    __table_args__ = (
        UniqueConstraint(
            "service_key",
            "allocation_version",
            name="uq_tenant_allocation_run_service_version",
        ),
        Index(
            "idx_tenant_allocation_runs_service_created",
            "service_key",
            "created_at",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    service_key: Mapped[str] = mapped_column(String(100), nullable=False)
    allocation_version: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
    )
    global_capacity: Mapped[float] = mapped_column(
        Numeric(14, 3),
        nullable=False,
    )
    evaluation_metrics: Mapped[dict] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )


class TenantAllocationResultRecord(Base):
    __tablename__ = "tenant_allocation_results"
    __table_args__ = (
        UniqueConstraint(
            "allocation_run_id",
            "tenant_id",
            name="uq_tenant_allocation_result_run_tenant",
        ),
        Index(
            "idx_tenant_allocation_results_service_created",
            "service_key",
            "created_at",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    allocation_run_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenant_allocation_runs.id"),
        nullable=False,
    )
    service_key: Mapped[str] = mapped_column(String(100), nullable=False)
    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False)
    allocation_rate: Mapped[float] = mapped_column(
        Numeric(14, 3),
        nullable=False,
    )
    predicted_demand: Mapped[float] = mapped_column(
        Numeric(14, 3),
        nullable=False,
    )
    current_allocation: Mapped[float] = mapped_column(
        Numeric(14, 3),
        nullable=False,
    )
    priority: Mapped[int] = mapped_column(Integer, nullable=False)
    weight: Mapped[float] = mapped_column(Numeric(14, 3), nullable=False)
    minimum_rate: Mapped[float] = mapped_column(Numeric(14, 3), nullable=False)
    maximum_rate: Mapped[float] = mapped_column(Numeric(14, 3), nullable=False)
    adaptive_enabled: Mapped[bool] = mapped_column(nullable=False)
    global_capacity: Mapped[float] = mapped_column(
        Numeric(14, 3),
        nullable=False,
    )
    allocation_version: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )


class RouteAllocationConfigRecord(Base):
    __tablename__ = "route_allocation_configs"
    __table_args__ = (
        UniqueConstraint(
            "service_key",
            "tenant_id",
            "route_id",
            name="uq_route_allocation_config_scope",
        ),
        Index(
            "idx_route_allocation_configs_service_tenant_route",
            "service_key",
            "tenant_id",
            "route_id",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    service_key: Mapped[str] = mapped_column(String(100), nullable=False)
    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False)
    route_id: Mapped[str] = mapped_column(String(128), nullable=False)
    route_weight: Mapped[float] = mapped_column(Numeric(14, 3), nullable=False)
    minimum_rate: Mapped[float] = mapped_column(Numeric(14, 3), nullable=False)
    maximum_rate: Mapped[float] = mapped_column(Numeric(14, 3), nullable=False)
    resource_cost_factor: Mapped[float] = mapped_column(
        Numeric(14, 6),
        nullable=False,
    )
    predicted_demand: Mapped[float] = mapped_column(
        Numeric(14, 3),
        nullable=False,
    )
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    adaptive_enabled: Mapped[bool] = mapped_column(nullable=False, default=True)
    current_allocation: Mapped[float] = mapped_column(
        Numeric(14, 3),
        nullable=False,
        default=0,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )


class RouteAllocationRunRecord(Base):
    __tablename__ = "route_allocation_runs"
    __table_args__ = (
        UniqueConstraint(
            "service_key",
            "allocation_version",
            name="uq_route_allocation_run_service_version",
        ),
        Index(
            "idx_route_allocation_runs_service_created",
            "service_key",
            "created_at",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    service_key: Mapped[str] = mapped_column(String(100), nullable=False)
    allocation_version: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
    )
    tenant_allocation_run_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenant_allocation_runs.id"),
        nullable=False,
    )
    global_capacity: Mapped[float] = mapped_column(
        Numeric(14, 3),
        nullable=False,
    )
    backend_resource_budget: Mapped[float] = mapped_column(
        Numeric(14, 3),
        nullable=False,
    )
    evaluation_metrics: Mapped[dict] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )


class RouteAllocationResultRecord(Base):
    __tablename__ = "route_allocation_results"
    __table_args__ = (
        UniqueConstraint(
            "allocation_run_id",
            "tenant_id",
            "route_id",
            name="uq_route_allocation_result_run_scope",
        ),
        Index(
            "idx_route_allocation_results_service_tenant_route",
            "service_key",
            "tenant_id",
            "route_id",
        ),
        Index(
            "idx_route_allocation_results_service_created",
            "service_key",
            "created_at",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    allocation_run_id: Mapped[UUID] = mapped_column(
        ForeignKey("route_allocation_runs.id"),
        nullable=False,
    )
    service_key: Mapped[str] = mapped_column(String(100), nullable=False)
    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False)
    route_id: Mapped[str] = mapped_column(String(128), nullable=False)
    allocated_rate: Mapped[float] = mapped_column(
        Numeric(14, 3),
        nullable=False,
    )
    predicted_demand: Mapped[float] = mapped_column(
        Numeric(14, 3),
        nullable=False,
    )
    estimated_resource_usage: Mapped[float] = mapped_column(
        Numeric(20, 6),
        nullable=False,
    )
    tenant_allocation_limit: Mapped[float] = mapped_column(
        Numeric(14, 3),
        nullable=False,
    )
    route_weight: Mapped[float] = mapped_column(Numeric(14, 3), nullable=False)
    resource_cost_factor: Mapped[float] = mapped_column(
        Numeric(14, 6),
        nullable=False,
    )
    priority: Mapped[int] = mapped_column(Integer, nullable=False)
    minimum_rate: Mapped[float] = mapped_column(Numeric(14, 3), nullable=False)
    maximum_rate: Mapped[float] = mapped_column(Numeric(14, 3), nullable=False)
    adaptive_enabled: Mapped[bool] = mapped_column(nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )


class TenantSlaConfigRecord(Base):
    __tablename__ = "tenant_sla_configs"
    __table_args__ = (
        UniqueConstraint(
            "service_key",
            "tenant_id",
            name="uq_tenant_sla_service_tenant",
        ),
        Index(
            "idx_tenant_sla_configs_service_tenant",
            "service_key",
            "tenant_id",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    service_key: Mapped[str] = mapped_column(String(100), nullable=False)
    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False)
    tier: Mapped[str] = mapped_column(String(20), nullable=False)
    priority: Mapped[int] = mapped_column(Integer, nullable=False)
    allocation_weight: Mapped[float] = mapped_column(
        Numeric(14, 3),
        nullable=False,
    )
    minimum_guaranteed_rate: Mapped[float] = mapped_column(
        Numeric(14, 3),
        nullable=False,
    )
    maximum_rate: Mapped[float] = mapped_column(Numeric(14, 3), nullable=False)
    max_throttle_ratio: Mapped[float] = mapped_column(
        Numeric(8, 6),
        nullable=False,
    )
    tenant_burst_capacity: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )
    availability_target: Mapped[float] = mapped_column(
        Numeric(8, 6),
        nullable=False,
    )
    adaptive_enabled: Mapped[bool] = mapped_column(nullable=False)
    predicted_demand: Mapped[float] = mapped_column(
        Numeric(14, 3),
        nullable=False,
    )
    config_version: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        default=1,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )


class TenantSlaConfigVersionRecord(Base):
    __tablename__ = "tenant_sla_config_versions"
    __table_args__ = (
        UniqueConstraint(
            "config_id",
            "config_version",
            name="uq_tenant_sla_config_version",
        ),
        Index(
            "idx_tenant_sla_versions_config_created",
            "config_id",
            "created_at",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    config_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenant_sla_configs.id"),
        nullable=False,
    )
    service_key: Mapped[str] = mapped_column(String(100), nullable=False)
    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False)
    config_version: Mapped[int] = mapped_column(BigInteger, nullable=False)
    tier: Mapped[str] = mapped_column(String(20), nullable=False)
    priority: Mapped[int] = mapped_column(Integer, nullable=False)
    allocation_weight: Mapped[float] = mapped_column(
        Numeric(14, 3),
        nullable=False,
    )
    minimum_guaranteed_rate: Mapped[float] = mapped_column(
        Numeric(14, 3),
        nullable=False,
    )
    maximum_rate: Mapped[float] = mapped_column(Numeric(14, 3), nullable=False)
    max_throttle_ratio: Mapped[float] = mapped_column(
        Numeric(8, 6),
        nullable=False,
    )
    tenant_burst_capacity: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )
    availability_target: Mapped[float] = mapped_column(
        Numeric(8, 6),
        nullable=False,
    )
    adaptive_enabled: Mapped[bool] = mapped_column(nullable=False)
    predicted_demand: Mapped[float] = mapped_column(
        Numeric(14, 3),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )


class TenantSlaAllocationRunRecord(Base):
    __tablename__ = "tenant_sla_allocation_runs"
    __table_args__ = (
        UniqueConstraint(
            "service_key",
            "allocation_version",
            name="uq_tenant_sla_run_service_version",
        ),
        Index(
            "idx_tenant_sla_runs_service_created",
            "service_key",
            "created_at",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    service_key: Mapped[str] = mapped_column(String(100), nullable=False)
    allocation_version: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
    )
    global_capacity: Mapped[float] = mapped_column(
        Numeric(14, 3),
        nullable=False,
    )
    evaluation_metrics: Mapped[dict] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )


class TenantSlaAllocationResultRecord(Base):
    __tablename__ = "tenant_sla_allocation_results"
    __table_args__ = (
        UniqueConstraint(
            "allocation_run_id",
            "tenant_id",
            name="uq_tenant_sla_result_run_tenant",
        ),
        Index(
            "idx_tenant_sla_results_service_tenant_created",
            "service_key",
            "tenant_id",
            "created_at",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    allocation_run_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenant_sla_allocation_runs.id"),
        nullable=False,
    )
    config_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenant_sla_config_versions.id"),
        nullable=False,
    )
    service_key: Mapped[str] = mapped_column(String(100), nullable=False)
    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False)
    config_version: Mapped[int] = mapped_column(BigInteger, nullable=False)
    tier: Mapped[str] = mapped_column(String(20), nullable=False)
    priority: Mapped[int] = mapped_column(Integer, nullable=False)
    allocation_weight: Mapped[float] = mapped_column(
        Numeric(14, 3),
        nullable=False,
    )
    guaranteed_rate: Mapped[float] = mapped_column(
        Numeric(14, 3),
        nullable=False,
    )
    allocated_rate: Mapped[float] = mapped_column(
        Numeric(14, 3),
        nullable=False,
    )
    maximum_rate: Mapped[float] = mapped_column(Numeric(14, 3), nullable=False)
    predicted_demand: Mapped[float] = mapped_column(
        Numeric(14, 3),
        nullable=False,
    )
    max_throttle_ratio: Mapped[float] = mapped_column(
        Numeric(8, 6),
        nullable=False,
    )
    tenant_burst_capacity: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )
    availability_target: Mapped[float] = mapped_column(
        Numeric(8, 6),
        nullable=False,
    )
    adaptive_enabled: Mapped[bool] = mapped_column(nullable=False)
    projected_throttle_ratio: Mapped[float] = mapped_column(
        Numeric(8, 6),
        nullable=False,
    )
    resource_usage: Mapped[float | None] = mapped_column(Numeric(20, 6))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )


class BenchmarkRunRecord(Base):
    __tablename__ = "benchmark_runs"
    __table_args__ = (
        UniqueConstraint(
            "batch_id",
            "strategy",
            name="uq_benchmark_run_batch_strategy",
        ),
        Index(
            "idx_benchmark_runs_service_scenario_created",
            "service_key",
            "scenario",
            "created_at",
        ),
        Index("idx_benchmark_runs_batch", "batch_id"),
        Index(
            "idx_benchmark_runs_status_created",
            "status",
            "created_at",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    batch_id: Mapped[UUID] = mapped_column(nullable=False)
    execution_order: Mapped[int] = mapped_column(Integer, nullable=False)
    strategy: Mapped[str] = mapped_column(String(32), nullable=False)
    scenario: Mapped[str] = mapped_column(String(40), nullable=False)
    service_key: Mapped[str] = mapped_column(String(100), nullable=False)
    environment_id: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    config_version: Mapped[str] = mapped_column(String(200), nullable=False)
    git_commit: Mapped[str] = mapped_column(String(80), nullable=False)
    k6_script_version: Mapped[str] = mapped_column(String(40), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    duration_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    warmup_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    tenant_count: Mapped[int] = mapped_column(Integer, nullable=False)
    start_rps: Mapped[int] = mapped_column(Integer, nullable=False)
    peak_rps: Mapped[int] = mapped_column(Integer, nullable=False)
    fault_injection_confirmed: Mapped[bool] = mapped_column(
        nullable=False,
        default=False,
    )
    slo_thresholds: Mapped[dict] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"),
        nullable=False,
    )
    workload_parameters: Mapped[dict] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"),
        nullable=False,
    )
    error: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )


class BenchmarkResultRecord(Base):
    __tablename__ = "benchmark_results"
    __table_args__ = (
        UniqueConstraint("run_id", name="uq_benchmark_result_run"),
        Index("idx_benchmark_results_run", "run_id"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    run_id: Mapped[UUID] = mapped_column(
        ForeignKey("benchmark_runs.id"),
        nullable=False,
    )
    incoming_rps: Mapped[float | None] = mapped_column(Numeric(14, 3))
    accepted_rps: Mapped[float | None] = mapped_column(Numeric(14, 3))
    successful_rps: Mapped[float | None] = mapped_column(Numeric(14, 3))
    p50_latency_ms: Mapped[float | None] = mapped_column(Numeric(14, 3))
    p95_latency_ms: Mapped[float | None] = mapped_column(Numeric(14, 3))
    p99_latency_ms: Mapped[float | None] = mapped_column(Numeric(14, 3))
    backend_p95_latency_ms: Mapped[float | None] = mapped_column(
        Numeric(14, 3)
    )
    rejection_ratio: Mapped[float | None] = mapped_column(Numeric(10, 6))
    backend_error_ratio: Mapped[float | None] = mapped_column(
        Numeric(10, 6)
    )
    cpu_usage: Mapped[float | None] = mapped_column(Numeric(10, 6))
    gateway_cpu_usage: Mapped[float | None] = mapped_column(Numeric(10, 6))
    memory_usage: Mapped[float | None] = mapped_column(Numeric(10, 6))
    gateway_memory_usage: Mapped[float | None] = mapped_column(
        Numeric(10, 6)
    )
    redis_latency_ms: Mapped[float | None] = mapped_column(Numeric(14, 3))
    sla_violation_count: Mapped[int | None] = mapped_column(BigInteger)
    fairness_index: Mapped[float | None] = mapped_column(Numeric(10, 6))
    fairness_basis: Mapped[str | None] = mapped_column(String(60))
    tenant_fairness_details: Mapped[dict | None] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql")
    )
    allocation_proposal_fairness_index: Mapped[float | None] = mapped_column(
        Numeric(10, 6)
    )
    policy_changes: Mapped[int | None] = mapped_column(Integer)
    stabilization_time_seconds: Mapped[float | None] = mapped_column(
        Numeric(14, 3)
    )
    redis_commands_per_second: Mapped[float | None] = mapped_column(
        Numeric(14, 3)
    )
    redis_connection_count: Mapped[int | None] = mapped_column(Integer)
    redis_memory_bytes: Mapped[int | None] = mapped_column(BigInteger)
    redis_error_count: Mapped[int | None] = mapped_column(BigInteger)
    redis_hot_key_observation: Mapped[str | None] = mapped_column(String)
    forecast_mae: Mapped[float | None] = mapped_column(Numeric(14, 6))
    forecast_wape: Mapped[float | None] = mapped_column(Numeric(14, 6))
    recommendation_generation_ms: Mapped[float | None] = mapped_column(
        Numeric(14, 3)
    )
    policy_application_ms: Mapped[float | None] = mapped_column(
        Numeric(14, 3)
    )
    propagation_delay_ms: Mapped[float | None] = mapped_column(
        Numeric(14, 3)
    )
    oscillation_frequency: Mapped[float | None] = mapped_column(
        Numeric(14, 6)
    )
    prometheus_query_reference: Mapped[str | None] = mapped_column(String)
    metrics_collection_errors: Mapped[list[str]] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"),
        nullable=False,
        default=list,
    )
    dropped_iterations: Mapped[int | None] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
