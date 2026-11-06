from decimal import Decimal, ROUND_DOWN

from app.sla_allocation.guarantee_validator import validate_guarantees
from app.sla_allocation.priority_calculator import effective_priority_weight
from app.sla_allocation.schemas import TenantSlaConfigInput

_QUANTUM = Decimal("0.001")
_ZERO = Decimal(0)


def allocate_sla_capacity(
    tenants: list[TenantSlaConfigInput],
    capacity: Decimal,
) -> dict[str, Decimal]:
    validate_guarantees(tenants, capacity)
    ordered = sorted(tenants, key=lambda item: item.tenant_id)
    allocations = {
        item.tenant_id: item.minimum_guaranteed_rate
        for item in ordered
    }
    caps = {
        item.tenant_id: (
            min(item.maximum_rate, item.predicted_demand)
            if item.adaptive_enabled
            else item.minimum_guaranteed_rate
        )
        for item in ordered
    }
    remaining = capacity - sum(allocations.values(), _ZERO)
    active = [
        item
        for item in ordered
        if item.adaptive_enabled
        and caps[item.tenant_id] > allocations[item.tenant_id]
    ]

    while active and remaining >= _QUANTUM:
        total_weight = sum(
            (effective_priority_weight(item) for item in active),
            _ZERO,
        )
        saturated = []
        for item in active:
            share = (
                remaining
                * effective_priority_weight(item)
                / total_weight
            )
            if caps[item.tenant_id] - allocations[item.tenant_id] <= share:
                saturated.append(item)
        if saturated:
            for item in saturated:
                grant = min(
                    caps[item.tenant_id] - allocations[item.tenant_id],
                    remaining,
                ).quantize(_QUANTUM, rounding=ROUND_DOWN)
                allocations[item.tenant_id] += grant
                remaining -= grant
            saturated_ids = {item.tenant_id for item in saturated}
            active = [
                item for item in active if item.tenant_id not in saturated_ids
            ]
            continue

        fractional = {}
        distributed = _ZERO
        for item in active:
            share = (
                remaining
                * effective_priority_weight(item)
                / total_weight
            )
            grant = share.quantize(_QUANTUM, rounding=ROUND_DOWN)
            fractional[item.tenant_id] = (grant, share - grant)
            distributed += grant
        for item in active:
            allocations[item.tenant_id] += fractional[item.tenant_id][0]
        remaining -= distributed
        for item in sorted(
            active,
            key=lambda tenant: (
                -fractional[tenant.tenant_id][1],
                tenant.tenant_id,
            ),
        ):
            if remaining < _QUANTUM:
                break
            if allocations[item.tenant_id] + _QUANTUM <= caps[item.tenant_id]:
                allocations[item.tenant_id] += _QUANTUM
                remaining -= _QUANTUM
        if distributed == 0:
            break
        if all(
            allocations[item.tenant_id] >= caps[item.tenant_id]
            for item in active
        ):
            break

    if sum(allocations.values(), _ZERO) > capacity:
        raise RuntimeError("SLA allocator exceeded global service capacity")
    if any(allocations[item.tenant_id] < item.minimum_guaranteed_rate
           for item in ordered if item.adaptive_enabled):
        raise RuntimeError("SLA allocator violated a configured guarantee")
    if any(allocations[item.tenant_id] > item.maximum_rate for item in ordered):
        raise RuntimeError("SLA allocator exceeded a tenant maximum")
    return allocations
