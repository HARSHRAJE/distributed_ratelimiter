from datetime import datetime
from enum import Enum
import math
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class RecommendationAction(str, Enum):
    INCREASE = "INCREASE"
    DECREASE = "DECREASE"
    HOLD = "HOLD"


class RecommendationStatus(str, Enum):
    PENDING = "PENDING"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


class RecommendationEvaluationInput(BaseModel):
    current_rate: float = Field(gt=0)
    min_refill_rate: float = Field(gt=0)
    max_refill_rate: float = Field(gt=0)
    hard_max_refill_rate: float = Field(gt=0)
    safe_capacity_rps: float = Field(gt=0)
    forecast_rps: float = Field(ge=0)
    forecast_confidence: float = Field(ge=0, le=1)
    policy_version: int = Field(ge=1)
    telemetry_timestamp: datetime
    cpu_utilization: float = Field(ge=0, le=100)
    p95_latency_ms: float = Field(ge=0)
    p99_latency_ms: float = Field(ge=0)
    error_rate: float = Field(ge=0)
    queue_depth: float = Field(ge=0)

    @model_validator(mode="after")
    def validate_policy_bounds(self) -> "RecommendationEvaluationInput":
        if self.min_refill_rate > self.max_refill_rate:
            raise ValueError("min_refill_rate cannot exceed max_refill_rate")
        if not self.min_refill_rate <= self.current_rate <= min(
            self.max_refill_rate,
            self.hard_max_refill_rate,
        ):
            raise ValueError(
                "current_rate must be between min_refill_rate and the effective maximum"
            )
        for value in self.model_dump().values():
            if isinstance(value, float) and not math.isfinite(value):
                raise ValueError("Recommendation inputs must be finite")
        return self


class RecommendationRecordSchema(BaseModel):
    id: UUID
    service_key: str
    scope: str
    current_rate: float
    recommended_rate: float
    action: RecommendationAction
    reason: str
    forecast_rps: float
    forecast_confidence: float
    safe_capacity_rps: float
    policy_version: int
    status: RecommendationStatus
    generated_at: datetime
    expires_at: datetime

    model_config = ConfigDict(from_attributes=True)


class RecommendationHistory(BaseModel):
    service_key: str
    recommendations: list[RecommendationRecordSchema]


class RecommendationApproval(BaseModel):
    current_policy_version: int = Field(ge=1)
