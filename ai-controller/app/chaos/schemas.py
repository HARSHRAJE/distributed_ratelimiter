from datetime import datetime
from enum import Enum
from uuid import UUID

from pydantic import BaseModel, Field, model_validator


class ChaosExperimentCode(str, Enum):
    CH_01 = "CH-01"
    CH_02 = "CH-02"
    CH_03 = "CH-03"
    CH_04 = "CH-04"
    CH_05 = "CH-05"
    CH_06 = "CH-06"
    CH_07 = "CH-07"
    CH_08 = "CH-08"
    CH_09 = "CH-09"
    CH_10 = "CH-10"


SCENARIO_DETAILS = {
    ChaosExperimentCode.CH_01: ("Redis unavailable", "redis"),
    ChaosExperimentCode.CH_02: ("Redis high latency", "redis"),
    ChaosExperimentCode.CH_03: ("One Gateway replica crashes", "gateway"),
    ChaosExperimentCode.CH_04: ("All Gateway replicas restart", "gateway"),
    ChaosExperimentCode.CH_05: ("Policy Service unavailable", "policy-service"),
    ChaosExperimentCode.CH_06: ("PostgreSQL unavailable", "postgres"),
    ChaosExperimentCode.CH_07: ("AI Controller crashes", "ai-controller-api"),
    ChaosExperimentCode.CH_08: ("Outbox dispatcher crashes", "outbox-dispatcher"),
    ChaosExperimentCode.CH_09: ("Redis policy synchronization delayed", "redis"),
    ChaosExperimentCode.CH_10: ("Network partition", "network"),
}


class ChaosExperimentRequest(BaseModel):
    experiment_code: ChaosExperimentCode
    test_environment_id: str = Field(
        min_length=1,
        max_length=100,
        pattern=r"^[A-Za-z0-9._-]+$",
    )
    service_key: str = Field(min_length=1, max_length=100)
    fault_duration_seconds: int | None = Field(default=None, ge=1, le=30)
    confirm_isolated_environment: bool = False
    confirm_gateway_traffic_is_test_traffic: bool = False
    operator_note: str = Field(default="", max_length=500)

    @model_validator(mode="after")
    def require_test_confirmation(self):
        if not self.confirm_isolated_environment:
            raise ValueError("Isolated test environment confirmation required")
        if not self.confirm_gateway_traffic_is_test_traffic:
            raise ValueError("Test-traffic confirmation required")
        return self


class ChaosExperiment(BaseModel):
    id: UUID
    experiment_code: ChaosExperimentCode
    scenario: str
    target_component: str
    service_key: str
    test_environment_id: str
    status: str
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime
    fault_duration_seconds: int
    operator_note: str
    error: str | None

    model_config = {"from_attributes": True}


class ChaosExperimentResult(BaseModel):
    id: UUID
    experiment_id: UUID
    requests_sent: int
    accepted_requests: int
    rejected_requests: int
    backend_errors: int
    gateway_errors: int
    policy_consistency: bool
    recovery_success: bool
    recovery_time_ms: int | None
    safety_violations: int
    details: dict
    created_at: datetime

    model_config = {"from_attributes": True}


class ChaosExperimentDetails(BaseModel):
    experiment: ChaosExperiment
    result: ChaosExperimentResult | None


class ChaosExperimentHistory(BaseModel):
    experiments: list[ChaosExperiment]
