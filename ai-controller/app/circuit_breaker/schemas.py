from datetime import datetime
from enum import Enum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.circuit_breaker.breaker_state import BreakerState


class ComponentName(str, Enum):
    TELEMETRY = "TELEMETRY"
    FORECASTING = "FORECASTING"
    POLICY_SERVICE = "POLICY_SERVICE"
    REDIS_SYNC = "REDIS_SYNC"
    EXECUTION = "EXECUTION"


class BreakerEvent(BaseModel):
    id: UUID
    service_key: str
    from_state: BreakerState
    to_state: BreakerState
    reason: str
    actor: str
    created_at: datetime


class ComponentHealth(BaseModel):
    service_key: str
    component: ComponentName
    state: BreakerState
    failure_count: int
    last_failure_reason: str | None
    next_attempt_at: datetime | None
    updated_at: datetime


class BreakerStatus(BaseModel):
    service_key: str
    state: BreakerState
    failure_count: int
    success_count: int
    opened_at: datetime | None
    next_attempt_at: datetime | None
    last_failure_reason: str | None
    manual_disabled: bool
    components: list[ComponentHealth]
    checks: list[str]
    updated_at: datetime


class BreakerHistory(BaseModel):
    service_key: str
    events: list[BreakerEvent]


class ManualRecoveryRequest(BaseModel):
    clear_manual_disable: bool = False


class ManualOpenRequest(BaseModel):
    reason: str = Field(
        default="Administrator manually disabled adaptive control",
        min_length=1,
        max_length=1000,
    )


class ExecutionReservation(BaseModel):
    id: UUID
    service_key: str
    recommendation_id: UUID
    recovery_check: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
