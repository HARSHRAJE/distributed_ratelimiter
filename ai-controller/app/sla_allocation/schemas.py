from datetime import datetime
from decimal import Decimal
from enum import Enum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ServiceTier(str, Enum):
    BASIC = "BASIC"
    PRO = "PRO"
    ENTERPRISE = "ENTERPRISE"


TIER_DEFAULTS = {
    ServiceTier.BASIC: {
        "priority": 1,
        "allocation_weight": Decimal("1"),
        "minimum_guaranteed_rate": Decimal("50"),
        "maximum_rate": Decimal("150"),
    },
    ServiceTier.PRO: {
        "priority": 2,
        "allocation_weight": Decimal("2"),
        "minimum_guaranteed_rate": Decimal("100"),
        "maximum_rate": Decimal("400"),
    },
    ServiceTier.ENTERPRISE: {
        "priority": 3,
        "allocation_weight": Decimal("4"),
        "minimum_guaranteed_rate": Decimal("200"),
        "maximum_rate": Decimal("800"),
    },
}


class TenantSlaConfigInput(BaseModel):
    tenant_id: str = Field(min_length=1, max_length=128)
    tier: ServiceTier
    priority: int | None = Field(default=None, ge=1)
    allocation_weight: Decimal | None = Field(
        default=None,
        gt=0,
        max_digits=14,
        decimal_places=3,
    )
    minimum_guaranteed_rate: Decimal | None = Field(
        default=None,
        ge=0,
        max_digits=14,
        decimal_places=3,
    )
    maximum_rate: Decimal | None = Field(
        default=None,
        gt=0,
        max_digits=14,
        decimal_places=3,
    )
    max_throttle_ratio: Decimal = Field(
        default=Decimal("0.05"),
        ge=0,
        le=1,
        max_digits=8,
        decimal_places=6,
    )
    tenant_burst_capacity: int = Field(default=1, gt=0)
    availability_target: Decimal = Field(
        default=Decimal("0.999"),
        gt=0,
        le=1,
        max_digits=8,
        decimal_places=6,
    )
    adaptive_enabled: bool = True
    predicted_demand: Decimal = Field(
        default=Decimal(0),
        ge=0,
        max_digits=14,
        decimal_places=3,
    )

    @model_validator(mode="after")
    def apply_tier_defaults(self):
        defaults = TIER_DEFAULTS[self.tier]
        for field in (
            "priority",
            "allocation_weight",
            "minimum_guaranteed_rate",
            "maximum_rate",
        ):
            if getattr(self, field) is None:
                setattr(self, field, defaults[field])
        if self.minimum_guaranteed_rate > self.maximum_rate:
            raise ValueError(
                "minimum_guaranteed_rate cannot exceed maximum_rate"
            )
        return self


class TenantSlaConfigList(BaseModel):
    tenants: list[TenantSlaConfigInput] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_tenants(self):
        tenant_ids = [item.tenant_id for item in self.tenants]
        if len(tenant_ids) != len(set(tenant_ids)):
            raise ValueError("tenant_id values must be unique")
        return self


class SlaEvaluationRequest(BaseModel):
    global_service_capacity: Decimal = Field(
        gt=0,
        max_digits=14,
        decimal_places=3,
    )


class TenantSlaConfig(BaseModel):
    id: UUID
    service_key: str
    tenant_id: str
    tier: ServiceTier
    priority: int
    allocation_weight: Decimal
    minimum_guaranteed_rate: Decimal
    maximum_rate: Decimal
    max_throttle_ratio: Decimal
    tenant_burst_capacity: int
    availability_target: Decimal
    adaptive_enabled: bool
    predicted_demand: Decimal
    config_version: int
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class SlaTenantAllocation(BaseModel):
    tenant_id: str
    tier: ServiceTier
    priority: int
    allocation_weight: Decimal
    config_version: int
    guaranteed_rate: Decimal
    allocated_rate: Decimal
    maximum_rate: Decimal
    predicted_demand: Decimal
    max_throttle_ratio: Decimal
    projected_throttle_ratio: Decimal
    projected_throttle_within_sla: bool
    estimated_resource_usage: Decimal | None
    guarantee_met: bool
    tenant_burst_capacity: int
    availability_target: Decimal
    adaptive_enabled: bool


class SlaAllocationMetrics(BaseModel):
    total_allocated_rps: Decimal
    global_capacity_utilization: Decimal
    guarantee_violations: int
    projected_throttle_violations: int
    weighted_allocation_fairness: Decimal


class SlaAllocationRun(BaseModel):
    allocation_run_id: UUID
    service_key: str
    allocation_version: int
    global_service_capacity: Decimal
    allocations: list[SlaTenantAllocation]
    metrics: SlaAllocationMetrics
    created_at: datetime


class SlaAllocationHistory(BaseModel):
    service_key: str
    runs: list[SlaAllocationRun]


class TenantSlaCompliance(BaseModel):
    tenant_id: str
    tier: ServiceTier
    config_version: int
    guaranteed_rate: Decimal
    proposed_allocation_rps: Decimal | None
    proposal_guarantee_violations: int
    actual_admitted_rps: Decimal | None
    actual_throttle_ratio: Decimal | None
    measured_resource_usage: Decimal | None
    p95_latency_ms: Decimal | None
    error_rate: Decimal | None
    availability: Decimal | None
    max_throttle_ratio: Decimal
    availability_target: Decimal
    sla_compliance: str = "NOT_MEASURABLE"
    measurement_note: str


class SlaComplianceReport(BaseModel):
    service_key: str
    allocation_run_id: UUID | None
    tenants: list[TenantSlaCompliance]
