from decimal import Decimal

from app.allocation.schemas import (
    AllocationMetrics,
    TenantAllocation,
    TenantAllocationConfig,
)


def jain_index(values: list[Decimal]) -> Decimal:
    if not values:
        return Decimal(1)
    total = sum(values, Decimal(0))
    squares = sum((value * value for value in values), Decimal(0))
    if squares == 0:
        return Decimal(1)
    return total * total / (Decimal(len(values)) * squares)


def evaluate_allocations(
    allocations: list[TenantAllocation],
    configs: list[TenantAllocationConfig],
    global_capacity: Decimal,
    *,
    previous_allocations: dict[str, Decimal] | None = None,
    starvation_seconds: int = 0,
) -> AllocationMetrics:
    total_allocated = sum(
        (item.allocation_rate for item in allocations),
        Decimal(0),
    )
    total_demand = sum(
        (item.predicted_demand for item in allocations),
        Decimal(0),
    )
    demand_fulfillment = []
    weighted_entitlement = []
    config_by_tenant = {item.tenant_id: item for item in configs}

    total_effective_weight = sum(
        (
            item.weight * Decimal(item.tenant_priority)
            for item in configs
            if item.adaptive_enabled
        ),
        Decimal(0),
    )
    available_after_minimums = max(
        Decimal(0),
        global_capacity
        - sum(
            (
                item.current_allocation
                if not item.adaptive_enabled
                else item.minimum_rate
                for item in configs
            ),
            Decimal(0),
        ),
    )
    oscillation = Decimal(0)
    for allocation in allocations:
        config = config_by_tenant[allocation.tenant_id]
        if allocation.predicted_demand > 0:
            demand_fulfillment.append(
                min(allocation.allocation_rate, allocation.predicted_demand)
                / allocation.predicted_demand
            )
        if config.adaptive_enabled and total_effective_weight > 0:
            entitlement = (
                available_after_minimums
                * config.weight
                * Decimal(config.tenant_priority)
                / total_effective_weight
            )
            if entitlement > 0:
                weighted_entitlement.append(
                    max(
                        Decimal(0),
                        allocation.allocation_rate - config.minimum_rate,
                    )
                    / entitlement
                )
        if previous_allocations is not None:
            oscillation += abs(
                allocation.allocation_rate
                - previous_allocations.get(
                    allocation.tenant_id,
                    allocation.current_allocation,
                )
            )

    rejected_demand = sum(
        (
            max(
                Decimal(0),
                item.predicted_demand - item.allocation_rate,
            )
            for item in allocations
        ),
        Decimal(0),
    )
    rejection_rate = (
        rejected_demand / total_demand
        if total_demand > 0
        else Decimal(0)
    )
    return AllocationMetrics(
        global_capacity_utilization=total_allocated / global_capacity,
        tenant_demand_fulfillment_jain_index=jain_index(demand_fulfillment),
        weighted_entitlement_jain_index=jain_index(weighted_entitlement),
        predicted_tenant_rejection_rate=rejection_rate,
        starvation_seconds=max(0, starvation_seconds),
        allocation_oscillation=(
            oscillation / global_capacity
            if previous_allocations is not None
            else Decimal(0)
        ),
    )
