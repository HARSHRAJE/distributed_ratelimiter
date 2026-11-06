from datetime import datetime
from enum import Enum
from uuid import UUID

from pydantic import BaseModel, Field


class ValidationStatus(str, Enum):
    VALID = "VALID"
    REJECTED = "REJECTED"


class ValidationRule(str, Enum):
    HARD_MAX_RATE = "HARD_MAX_RATE"
    MINIMUM_RATE = "MINIMUM_RATE"
    MAX_CHANGE_PERCENT = "MAX_CHANGE_PERCENT"
    POLICY_VERSION = "POLICY_VERSION"
    EXPIRATION = "EXPIRATION"
    TELEMETRY_FRESHNESS = "TELEMETRY_FRESHNESS"
    FORECAST_CONFIDENCE = "FORECAST_CONFIDENCE"
    COOLDOWN = "COOLDOWN"
    SERVICE_STATUS = "SERVICE_STATUS"
    SAFE_CAPACITY = "SAFE_CAPACITY"
    RECOMMENDATION_STATUS = "RECOMMENDATION_STATUS"


class ValidationCheck(BaseModel):
    rule: ValidationRule
    passed: bool
    message: str


class ValidationContext(BaseModel):
    current_rate: float = Field(gt=0)
    min_refill_rate: float = Field(gt=0)
    hard_max_refill_rate: float = Field(gt=0)
    current_policy_version: int = Field(ge=1)
    telemetry_timestamp: datetime
    adaptive_control_enabled: bool
    safe_capacity_rps: float = Field(gt=0)


class ValidationResult(BaseModel):
    id: UUID
    recommendation_id: UUID
    status: ValidationStatus
    checks: list[ValidationCheck]
    validated_at: datetime
    validator_version: str


class ValidationHistory(BaseModel):
    recommendation_id: UUID
    validations: list[ValidationResult]
