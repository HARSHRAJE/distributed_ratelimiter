from datetime import datetime
from enum import Enum
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class RollbackStatus(str, Enum):
    DETECTED = "DETECTED"
    INITIATED = "INITIATED"
    POLICY_RESTORED = "POLICY_RESTORED"
    REDIS_SYNCED = "REDIS_SYNCED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class RollbackTrigger(BaseModel):
    metric: str
    value: float
    threshold: float
    reason: str
    critical: bool = False


class RollbackEvaluation(BaseModel):
    service_key: str
    execution_id: UUID | None
    eligible: bool
    triggered: bool
    triggers: list[RollbackTrigger]
    message: str
    evaluated_at: datetime


class RollbackEvent(BaseModel):
    id: UUID
    execution_id: UUID
    service_key: str
    failed_version: int
    restored_from_version: int
    rollback_version: int | None
    trigger_metric: str
    trigger_value: float
    threshold_value: float
    reason: str
    status: RollbackStatus
    created_at: datetime
    completed_at: datetime | None
    effective_config_verified_at: datetime | None

    model_config = ConfigDict(from_attributes=True)


class RollbackHistory(BaseModel):
    service_key: str
    rollbacks: list[RollbackEvent]
