from decimal import Decimal

from app.sla_allocation.priority_calculator import effective_priority_weight
from app.sla_allocation.schemas import (
    SlaAllocationMetrics,
    SlaTenantAllocation,
    TenantSlaConfigInput,
)


def weighted_fairness(
    allocations: list[SlaTenantAllocation],
    configs: list[TenantSlaConfigInput],
) -> Decimal:
    config_by_id = {item.tenant_id: item for item in configs}
    ratios = []
    for allocation in allocations:
        config = config_by_id[allocation.tenant_id]
        if config.adaptive_enabled:
            extra = max(
                Decimal(0),
                allocation.allocated_rate - allocation.guaranteed_rate,
            )
            weight = effective_priority_weight(config)
            if weight > 0:
                ratios.append(extra / weight)
    if not ratios:
        return Decimal(1)
    total = sum(ratios, Decimal(0))
    squares = sum((value * value for value in ratios), Decimal(0))
    if squares == 0:
        return Decimal(1)
    return total * total / (Decimal(len(ratios)) * squares)


def evaluate_sla_allocations(
    configs: list[TenantSlaConfigInput],
    rates: dict[str, Decimal],
    *,
    capacity: Decimal,
    config_versions: dict[str, int],
) -> tuple[list[SlaTenantAllocation], SlaAllocationMetrics]:
    allocations = []
    for config in sorted(configs, key=lambda item: item.tenant_id):
        allocation = rates[config.tenant_id]
        demand = config.predicted_demand
        throttle = (
            max(Decimal(0), demand - allocation) / demand
            if demand > 0
            else Decimal(0)
        )
        allocations.append(
            SlaTenantAllocation(
                tenant_id=config.tenant_id,
                tier=config.tier,
                priority=config.priority,
                allocation_weight=config.allocation_weight,
                config_version=config_versions[config.tenant_id],
                guaranteed_rate=config.minimum_guaranteed_rate,
                allocated_rate=allocation,
                maximum_rate=config.maximum_rate,
                predicted_demand=demand,
                max_throttle_ratio=config.max_throttle_ratio,
                projected_throttle_ratio=throttle,
                projected_throttle_within_sla=(
                    throttle <= config.max_throttle_ratio
                ),
                estimated_resource_usage=None,
                guarantee_met=(
                    allocation >= config.minimum_guaranteed_rate
                    if config.adaptive_enabled
                    else True
                ),
                tenant_burst_capacity=config.tenant_burst_capacity,
                availability_target=config.availability_target,
                adaptive_enabled=config.adaptive_enabled,
            )
        )
    total_allocated = sum(
        (item.allocated_rate for item in allocations),
        Decimal(0),
    )
    return allocations, SlaAllocationMetrics(
        total_allocated_rps=total_allocated,
        global_capacity_utilization=total_allocated / capacity,
        guarantee_violations=sum(
            1 for item in allocations if not item.guarantee_met
        ),
        projected_throttle_violations=sum(
            1 for item in allocations
            if not item.projected_throttle_within_sla
        ),
        weighted_allocation_fairness=weighted_fairness(
            allocations,
            configs,
        ),
    )
