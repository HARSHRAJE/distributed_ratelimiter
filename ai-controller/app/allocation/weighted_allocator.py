from decimal import Decimal, ROUND_DOWN

from app.allocation.allocation_constraints import (
    validate_allocation_constraints,
)
from app.allocation.demand_analyzer import demand_ceiling
from app.allocation.schemas import TenantAllocation, TenantAllocationConfig

_QUANTUM = Decimal("0.001")
_ZERO = Decimal(0)


def weighted_water_fill(
    tenants: list[TenantAllocationConfig],
    global_capacity: Decimal,
) -> list[TenantAllocation]:
    validate_allocation_constraints(tenants, global_capacity)

    ordered = sorted(tenants, key=lambda tenant: tenant.tenant_id)
    allocations = {
        tenant.tenant_id: (
            tenant.current_allocation
            if not tenant.adaptive_enabled
            else tenant.minimum_rate
        )
        for tenant in ordered
    }
    capacity = global_capacity.quantize(_QUANTUM, rounding=ROUND_DOWN)
    remaining = capacity - sum(allocations.values(), _ZERO)
    active = [
        tenant
        for tenant in ordered
        if tenant.adaptive_enabled
        and demand_ceiling(tenant) > allocations[tenant.tenant_id]
    ]

    while active and remaining >= _QUANTUM:
        total_weight = sum(
            (
                tenant.weight * Decimal(tenant.tenant_priority)
                for tenant in active
            ),
            _ZERO,
        )
        saturated = []
        for tenant in active:
            share = remaining * (
                tenant.weight * Decimal(tenant.tenant_priority)
            ) / total_weight
            available = demand_ceiling(tenant) - allocations[tenant.tenant_id]
            if available <= share:
                saturated.append(tenant)
        if saturated:
            for tenant in saturated:
                available = demand_ceiling(tenant) - allocations[tenant.tenant_id]
                grant = min(available, remaining).quantize(
                    _QUANTUM,
                    rounding=ROUND_DOWN,
                )
                allocations[tenant.tenant_id] += grant
                remaining -= grant
            saturated_ids = {tenant.tenant_id for tenant in saturated}
            active = [
                tenant
                for tenant in active
                if tenant.tenant_id not in saturated_ids
            ]
            continue

        shares = {}
        distributed = _ZERO
        for tenant in active:
            exact_share = remaining * (
                tenant.weight * Decimal(tenant.tenant_priority)
            ) / total_weight
            grant = exact_share.quantize(_QUANTUM, rounding=ROUND_DOWN)
            shares[tenant.tenant_id] = (grant, exact_share - grant)
            distributed += grant
        for tenant in active:
            grant = shares[tenant.tenant_id][0]
            allocations[tenant.tenant_id] += grant
        remaining -= distributed

        # Hand out rounding units deterministically without exceeding a cap.
        for tenant in sorted(
            active,
            key=lambda item: (
                -shares[item.tenant_id][1],
                item.tenant_id,
            ),
        ):
            if remaining < _QUANTUM:
                break
            if allocations[tenant.tenant_id] + _QUANTUM <= demand_ceiling(tenant):
                allocations[tenant.tenant_id] += _QUANTUM
                remaining -= _QUANTUM
        if distributed == 0:
            break
        if all(
            allocations[tenant.tenant_id] >= demand_ceiling(tenant)
            for tenant in active
        ):
            break

    result = [
        TenantAllocation(
            tenant_id=tenant.tenant_id,
            allocation_rate=allocations[tenant.tenant_id],
            predicted_demand=tenant.predicted_demand,
            current_allocation=tenant.current_allocation,
            tenant_priority=tenant.tenant_priority,
            weight=tenant.weight,
        )
        for tenant in ordered
    ]
    if sum((item.allocation_rate for item in result), _ZERO) > capacity:
        raise RuntimeError("Weighted allocator exceeded global service capacity")
    return result
