from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


RATE = Field(gt=0, max_digits=14, decimal_places=3)
NON_NEGATIVE_RATE = Field(ge=0, max_digits=14, decimal_places=3)


class TenantAllocationConfig(BaseModel):
    tenant_id: str = Field(min_length=1, max_length=128)
    tenant_priority: int = Field(default=1, ge=1)
    weight: Decimal = Field(gt=0, max_digits=14, decimal_places=3)
    minimum_rate: Decimal = NON_NEGATIVE_RATE
    maximum_rate: Decimal = RATE
    adaptive_enabled: bool = True
    predicted_demand: Decimal = NON_NEGATIVE_RATE
    current_allocation: Decimal = NON_NEGATIVE_RATE

    @model_validator(mode="after")
    def validate_bounds(self):
        if self.minimum_rate > self.maximum_rate:
            raise ValueError("minimum_rate cannot exceed maximum_rate")
        if not self.adaptive_enabled and not (
            self.minimum_rate
            <= self.current_allocation
            <= self.maximum_rate
        ):
            raise ValueError(
                "A non-adaptive tenant's current allocation must be within "
                "its configured minimum and maximum"
            )
        return self


class TenantAllocationConfigList(BaseModel):
    tenants: list[TenantAllocationConfig] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_tenants(self):
        tenant_ids = [tenant.tenant_id for tenant in self.tenants]
        if len(tenant_ids) != len(set(tenant_ids)):
            raise ValueError("tenant_id values must be unique")
        return self


class AllocationEvaluationRequest(BaseModel):
    global_capacity_rps: Decimal = RATE


class TenantAllocation(BaseModel):
    tenant_id: str
    allocation_rate: Decimal
    predicted_demand: Decimal
    current_allocation: Decimal
    tenant_priority: int
    weight: Decimal


class AllocationMetrics(BaseModel):
    global_capacity_utilization: Decimal
    tenant_demand_fulfillment_jain_index: Decimal
    weighted_entitlement_jain_index: Decimal
    predicted_tenant_rejection_rate: Decimal
    starvation_seconds: int
    allocation_oscillation: Decimal


class AllocationRun(BaseModel):
    allocation_run_id: UUID
    service_key: str
    allocation_version: int
    global_capacity_rps: Decimal
    allocations: list[TenantAllocation]
    metrics: AllocationMetrics
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class AllocationHistory(BaseModel):
    service_key: str
    runs: list[AllocationRun]
