from datetime import datetime
from enum import Enum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ExecutionStatus(str, Enum):
    PENDING = "PENDING"
    VALIDATING = "VALIDATING"
    SUBMITTED = "SUBMITTED"
    APPLIED = "APPLIED"
    FAILED = "FAILED"
    ROLLBACK_PENDING = "ROLLBACK_PENDING"
    ROLLED_BACK = "ROLLED_BACK"


class ExecutionCheck(BaseModel):
    check: str
    passed: bool
    message: str


class ExecutionResult(BaseModel):
    id: UUID
    recommendation_id: UUID
    service_key: str
    policy_id: UUID | None
    previous_version: int
    resulting_version: int | None
    previous_rate: float
    proposed_rate: float
    status: ExecutionStatus
    failure_reason: str | None
    started_at: datetime
    completed_at: datetime | None
    checks: list[ExecutionCheck] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


class ExecutionHistory(BaseModel):
    service_key: str
    executions: list[ExecutionResult]


class ServiceControlRequest(BaseModel):
    manual_override: bool = False
    manual_approval: bool = False


class ServiceControlResult(BaseModel):
    service_key: str
    enabled: bool
    manual_override: bool
    rollout_started_at: datetime | None
    paused_reason: str | None
