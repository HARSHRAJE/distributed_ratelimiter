from decimal import Decimal, ROUND_DOWN

from app.route_allocation.resource_constraints import (
    validate_resource_constraints,
)
from app.route_allocation.route_cost_estimator import effective_route_weight
from app.route_allocation.route_demand_analyzer import route_demand_ceiling
from app.route_allocation.schemas import RouteAllocationConfig

_QUANTUM = Decimal("0.001")
_ZERO = Decimal(0)


def allocate_routes(
    configs: list[RouteAllocationConfig],
    tenant_limits: dict[str, Decimal],
    global_capacity: Decimal,
    backend_resource_budget: Decimal,
) -> dict[tuple[str, str], Decimal]:
    validate_resource_constraints(
        configs,
        tenant_limits,
        global_capacity,
        backend_resource_budget,
    )
    ordered = sorted(configs, key=lambda item: (item.tenant_id, item.route_id))
    rates = {
        (item.tenant_id, item.route_id): (
            item.current_allocation
            if not item.adaptive_enabled
            else item.route_minimum_rate
        )
        for item in ordered
    }
    caps = {
        (item.tenant_id, item.route_id): route_demand_ceiling(item)
        for item in ordered
    }
    effective_weights = {
        (item.tenant_id, item.route_id): (
            effective_route_weight(item) if item.adaptive_enabled else _ZERO
        )
        for item in ordered
    }
    total_rate = sum(rates.values(), _ZERO)
    resource_used = sum(
        (
            rates[(item.tenant_id, item.route_id)]
            * item.resource_cost_factor
            for item in ordered
        ),
        _ZERO,
    )
    active = [
        item
        for item in ordered
        if item.adaptive_enabled
        and rates[(item.tenant_id, item.route_id)]
        < caps[(item.tenant_id, item.route_id)]
    ]

    while active:
        tenant_totals: dict[str, Decimal] = {}
        for item in ordered:
            tenant_totals[item.tenant_id] = (
                tenant_totals.get(item.tenant_id, _ZERO)
                + rates[(item.tenant_id, item.route_id)]
            )
        active = [
            item
            for item in active
            if rates[(item.tenant_id, item.route_id)]
            < caps[(item.tenant_id, item.route_id)]
            and tenant_totals[item.tenant_id] < tenant_limits[item.tenant_id]
        ]
        if not active or total_rate >= global_capacity:
            break
        if resource_used >= backend_resource_budget:
            break
        active_weights = {
            (item.tenant_id, item.route_id): effective_weights[
                (item.tenant_id, item.route_id)
            ]
            for item in active
        }
        total_weight = sum(active_weights.values(), _ZERO)
        if total_weight <= 0:
            break
        tenant_weight: dict[str, Decimal] = {}
        for item in active:
            tenant_weight[item.tenant_id] = (
                tenant_weight.get(item.tenant_id, _ZERO)
                + active_weights[(item.tenant_id, item.route_id)]
            )

        boundaries = [
            (global_capacity - total_rate) / total_weight,
            (backend_resource_budget - resource_used)
            / sum(
                (
                    active_weights[(item.tenant_id, item.route_id)]
                    * item.resource_cost_factor
                    for item in active
                ),
                _ZERO,
            ),
        ]
        for item in active:
            key = (item.tenant_id, item.route_id)
            weight = active_weights[key]
            boundaries.append((caps[key] - rates[key]) / weight)
        for tenant_id, weight in tenant_weight.items():
            boundaries.append(
                (tenant_limits[tenant_id] - tenant_totals[tenant_id]) / weight
            )

        positive_boundaries = [value for value in boundaries if value > 0]
        if not positive_boundaries:
            break
        step = min(positive_boundaries)
        increments = {}
        for item in active:
            key = (item.tenant_id, item.route_id)
            raw_increment = step * active_weights[key]
            remaining_route = caps[key] - rates[key]
            increments[key] = min(
                raw_increment,
                remaining_route,
            ).quantize(_QUANTUM, rounding=ROUND_DOWN)
        changed = sum(increments.values(), _ZERO)
        if changed == 0:
            break
        for key, increment in increments.items():
            rates[key] += increment
        total_rate += changed
        resource_used = sum(
            (
                rates[(item.tenant_id, item.route_id)]
                * item.resource_cost_factor
                for item in ordered
            ),
            _ZERO,
        )

        # If rounding leaves room below a binding constraint, distribute one
        # unit at a time by weighted remainder, with a stable route tie-break.
        remainders = {
            (item.tenant_id, item.route_id): (
                step * active_weights[(item.tenant_id, item.route_id)]
                - increments[(item.tenant_id, item.route_id)]
            )
            for item in active
        }
        for item in sorted(
            active,
            key=lambda route: (
                -remainders[(route.tenant_id, route.route_id)],
                route.tenant_id,
                route.route_id,
            ),
        ):
            key = (item.tenant_id, item.route_id)
            if rates[key] + _QUANTUM > caps[key]:
                continue
            tenant_total = sum(
                (
                    rates[(route.tenant_id, route.route_id)]
                    for route in ordered
                    if route.tenant_id == item.tenant_id
                ),
                _ZERO,
            )
            if tenant_total + _QUANTUM > tenant_limits[item.tenant_id]:
                continue
            if total_rate + _QUANTUM > global_capacity:
                continue
            if (
                resource_used
                + _QUANTUM * item.resource_cost_factor
                > backend_resource_budget
            ):
                continue
            rates[key] += _QUANTUM
            total_rate += _QUANTUM
            resource_used += _QUANTUM * item.resource_cost_factor

        next_active = []
        tenant_totals = {}
        for item in ordered:
            tenant_totals[item.tenant_id] = (
                tenant_totals.get(item.tenant_id, _ZERO)
                + rates[(item.tenant_id, item.route_id)]
            )
        global_blocked = total_rate + _QUANTUM > global_capacity
        resource_blocked = resource_used >= backend_resource_budget
        for item in active:
            key = (item.tenant_id, item.route_id)
            tenant_blocked = (
                tenant_totals[item.tenant_id] + _QUANTUM
                > tenant_limits[item.tenant_id]
            )
            if (
                rates[key] < caps[key]
                and not tenant_blocked
                and not global_blocked
                and not resource_blocked
            ):
                next_active.append(item)
        if len(next_active) == len(active) and changed == 0:
            break
        active = next_active

    final_total = sum(rates.values(), _ZERO)
    final_resource = sum(
        (
            rates[(item.tenant_id, item.route_id)]
            * item.resource_cost_factor
            for item in ordered
        ),
        _ZERO,
    )
    if final_total > global_capacity or final_resource > backend_resource_budget:
        raise RuntimeError("Route allocator exceeded global resource constraints")
    for tenant_id, limit in tenant_limits.items():
        tenant_total = sum(
            (
                rates[(item.tenant_id, item.route_id)]
                for item in ordered
                if item.tenant_id == tenant_id
            ),
            _ZERO,
        )
        if tenant_total > limit:
            raise RuntimeError(
                f"Route allocator exceeded tenant allocation for {tenant_id}"
            )
    return rates
