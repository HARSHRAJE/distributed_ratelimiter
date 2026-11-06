from decimal import Decimal

from app.route_allocation.route_cost_estimator import (
    effective_route_weight,
    estimated_resource_usage,
)
from app.route_allocation.schemas import (
    RouteAllocation,
    RouteAllocationConfig,
    RouteAllocationMetrics,
)


def _jain_index(values: list[Decimal]) -> Decimal:
    if not values:
        return Decimal(1)
    total = sum(values, Decimal(0))
    squared = sum((value * value for value in values), Decimal(0))
    if squared == 0:
        return Decimal(1)
    return total * total / (Decimal(len(values)) * squared)


def evaluate_route_allocations(
    configs: list[RouteAllocationConfig],
    rates: dict[tuple[str, str], Decimal],
    tenant_limits: dict[str, Decimal],
    global_capacity: Decimal,
    backend_resource_budget: Decimal,
) -> tuple[list[RouteAllocation], RouteAllocationMetrics]:
    allocations = []
    tenant_totals: dict[str, Decimal] = {}
    demand_fulfillment = []
    weighted_entitlement = []
    total_rate = Decimal(0)
    resource_usage = Decimal(0)
    rejected_demand = Decimal(0)
    total_demand = Decimal(0)

    for config in sorted(
        configs,
        key=lambda item: (item.tenant_id, item.route_id),
    ):
        key = (config.tenant_id, config.route_id)
        rate = rates[key]
        resource = estimated_resource_usage(
            rate,
            config.resource_cost_factor,
        )
        allocations.append(
            RouteAllocation(
                tenant_id=config.tenant_id,
                route_id=config.route_id,
                allocated_rate=rate,
                predicted_demand=config.predicted_demand,
                tenant_allocation_limit=tenant_limits[config.tenant_id],
                estimated_resource_usage=resource,
                route_weight=config.route_weight,
                resource_cost_factor=config.resource_cost_factor,
                priority=config.priority,
                minimum_rate=config.route_minimum_rate,
                maximum_rate=config.route_maximum_rate,
                adaptive_enabled=config.adaptive_enabled,
            )
        )
        total_rate += rate
        resource_usage += resource
        tenant_totals[config.tenant_id] = (
            tenant_totals.get(config.tenant_id, Decimal(0)) + rate
        )
        demand = config.predicted_demand
        total_demand += demand
        rejected_demand += max(Decimal(0), demand - rate)
        if demand > 0:
            demand_fulfillment.append(min(rate, demand) / demand)
        if config.adaptive_enabled:
            entitlement_weight = effective_route_weight(config)
            if entitlement_weight > 0:
                weighted_entitlement.append(rate / entitlement_weight)

    return allocations, RouteAllocationMetrics(
        total_allocated_rps=total_rate,
        global_capacity_utilization=total_rate / global_capacity,
        estimated_resource_usage=resource_usage,
        backend_resource_utilization=resource_usage / backend_resource_budget,
        tenant_capacity_utilization={
            tenant_id: used / tenant_limits[tenant_id]
            if tenant_limits[tenant_id] > 0
            else Decimal(0)
            for tenant_id, used in sorted(tenant_totals.items())
        },
        demand_fulfillment_jain_index=_jain_index(demand_fulfillment),
        weighted_entitlement_jain_index=_jain_index(weighted_entitlement),
        predicted_rejection_rate=(
            rejected_demand / total_demand if total_demand else Decimal(0)
        ),
    )
