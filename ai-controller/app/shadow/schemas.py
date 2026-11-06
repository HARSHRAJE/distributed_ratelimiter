from datetime import datetime
from enum import Enum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, FiniteFloat


class BucketConfiguration(BaseModel):
    capacity: int = Field(ge=1)
    refill_rate_rps: FiniteFloat = Field(gt=0)


class ShadowEvaluationRequest(BaseModel):
    recommendation_id: UUID
    safe_capacity_rps: FiniteFloat = Field(gt=0)
    evaluation_window_seconds: int = Field(ge=1, le=3600)
    tenant_key: str = Field(min_length=1, max_length=128)
    route_key: str = Field(min_length=1, max_length=128)
    rule_based_rate: FiniteFloat = Field(gt=0)


class StrategyName(str, Enum):
    STATIC = "STATIC"
    RULE_BASED = "RULE_BASED"
    FORECAST_ASSISTED = "FORECAST_ASSISTED"


class TrafficPoint(BaseModel):
    timestamp: datetime
    window_seconds: int = Field(gt=0)
    incoming_rps: FiniteFloat = Field(ge=0)
    allowed_rps: FiniteFloat | None = Field(default=None, ge=0)
    rejected_rps: FiniteFloat | None = Field(default=None, ge=0)
    p95_latency_ms: FiniteFloat | None = Field(default=None, ge=0)
    p99_latency_ms: FiniteFloat | None = Field(default=None, ge=0)
    error_rate: FiniteFloat | None = Field(default=None, ge=0)
    cpu_utilization: FiniteFloat | None = Field(default=None, ge=0)


class StrategyOutcome(BaseModel):
    strategy: StrategyName
    applied_global_rate_rps: float
    estimated_admitted_rps: float
    estimated_rejected_rps: float
    actual_admitted_rps: float | None
    actual_rejected_rps: float | None
    observed_p95_latency_ms: float | None
    observed_p99_latency_ms: float | None
    observed_error_rate: float | None
    observed_cpu_utilization: float | None
    forecast_error_rps: float | None


class ShadowEvaluationResult(BaseModel):
    id: UUID
    recommendation_id: UUID
    service_key: str
    current_policy_version: int
    current_rate: float
    proposed_rate: float
    actual_incoming_rps: float
    estimated_admitted_rps: float
    estimated_rejected_rps: float
    evaluation_window_seconds: int
    strategies: list[StrategyOutcome]
    input_metadata: dict
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ShadowHistory(BaseModel):
    service_key: str
    evaluations: list[ShadowEvaluationResult]


class StrategyComparison(BaseModel):
    strategy: StrategyName
    evaluation_count: int
    mean_admitted_rps: float
    mean_rejected_rps: float
    mean_observed_p95_latency_ms: float | None
    mean_observed_p99_latency_ms: float | None
    mean_observed_error_rate: float | None
    mean_observed_cpu_utilization: float | None
    mean_forecast_error_rps: float | None
    policy_rate_changes: int


class ShadowComparison(BaseModel):
    service_key: str
    strategies: list[StrategyComparison]
