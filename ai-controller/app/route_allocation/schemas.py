from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class RouteAllocationConfig(BaseModel):
    tenant_id: str = Field(min_length=1, max_length=128)
    route_id: str = Field(min_length=1, max_length=128)
    route_weight: Decimal = Field(gt=0, max_digits=14, decimal_places=3)
    route_minimum_rate: Decimal = Field(ge=0, max_digits=14, decimal_places=3)
    route_maximum_rate: Decimal = Field(gt=0, max_digits=14, decimal_places=3)
    resource_cost_factor: Decimal = Field(
        gt=0,
        max_digits=14,
        decimal_places=6,
        description="Measured backend resource units consumed per request",
    )
    predicted_demand: Decimal = Field(ge=0, max_digits=14, decimal_places=3)
    priority: int = Field(default=1, ge=1)
    adaptive_enabled: bool = True
    current_allocation: Decimal = Field(
        default=Decimal(0),
        ge=0,
        max_digits=14,
        decimal_places=3,
    )

    @model_validator(mode="after")
    def validate_route_bounds(self):
        if self.route_minimum_rate > self.route_maximum_rate:
            raise ValueError(
                "route_minimum_rate cannot exceed route_maximum_rate"
            )
        if not self.adaptive_enabled and not (
            self.route_minimum_rate
            <= self.current_allocation
            <= self.route_maximum_rate
        ):
            raise ValueError(
                "A non-adaptive route's current allocation must be within "
                "its configured minimum and maximum"
            )
        return self


class RouteAllocationConfigList(BaseModel):
    routes: list[RouteAllocationConfig] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_routes(self):
        scopes = [(route.tenant_id, route.route_id) for route in self.routes]
        if len(scopes) != len(set(scopes)):
            raise ValueError("(tenant_id, route_id) values must be unique")
        return self


class RouteAllocationEvaluationRequest(BaseModel):
    backend_resource_budget: Decimal = Field(
        gt=0,
        max_digits=14,
        decimal_places=3,
        description="Load-test-calibrated resource units available per second",
    )


class RouteAllocation(BaseModel):
    tenant_id: str
    route_id: str
    allocated_rate: Decimal
    predicted_demand: Decimal
    tenant_allocation_limit: Decimal
    estimated_resource_usage: Decimal
    route_weight: Decimal
    resource_cost_factor: Decimal
    priority: int
    minimum_rate: Decimal
    maximum_rate: Decimal
    adaptive_enabled: bool


class RouteAllocationMetrics(BaseModel):
    total_allocated_rps: Decimal
    global_capacity_utilization: Decimal
    estimated_resource_usage: Decimal
    backend_resource_utilization: Decimal
    tenant_capacity_utilization: dict[str, Decimal]
    demand_fulfillment_jain_index: Decimal
    weighted_entitlement_jain_index: Decimal
    predicted_rejection_rate: Decimal


class RouteAllocationRun(BaseModel):
    allocation_run_id: UUID
    service_key: str
    allocation_version: int
    tenant_allocation_run_id: UUID
    global_capacity: Decimal
    backend_resource_budget: Decimal
    allocations: list[RouteAllocation]
    metrics: RouteAllocationMetrics
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class RouteAllocationHistory(BaseModel):
    service_key: str
    runs: list[RouteAllocationRun]


class RouteAllocationChange(BaseModel):
    tenant_id: str
    route_id: str
    previous_rate: Decimal
    proposed_rate: Decimal
    change_rate: Decimal


class RouteAllocationComparison(BaseModel):
    service_key: str
    previous_allocation_run_id: UUID
    proposed_allocation_run_id: UUID
    changes: list[RouteAllocationChange]
    previous_metrics: RouteAllocationMetrics
    proposed_metrics: RouteAllocationMetrics
