from decimal import Decimal

from app.route_allocation.route_cost_estimator import (
    estimated_resource_usage,
)
from app.route_allocation.schemas import RouteAllocationConfig


class RouteAllocationConstraintError(ValueError):
    pass


def validate_resource_constraints(
    configs: list[RouteAllocationConfig],
    tenant_limits: dict[str, Decimal],
    global_capacity: Decimal,
    backend_resource_budget: Decimal,
) -> None:
    if global_capacity <= 0 or backend_resource_budget <= 0:
        raise RouteAllocationConstraintError(
            "Global capacity and backend resource budget must be positive"
        )
    if not configs:
        raise RouteAllocationConstraintError(
            "At least one route allocation configuration is required"
        )
    routes = [(item.tenant_id, item.route_id) for item in configs]
    if len(routes) != len(set(routes)):
        raise RouteAllocationConstraintError(
            "(tenant_id, route_id) route configurations must be unique"
        )
    configured_tenants = {item.tenant_id for item in configs}
    if configured_tenants - tenant_limits.keys():
        missing = sorted(configured_tenants - tenant_limits.keys())
        raise RouteAllocationConstraintError(
            "Tenant allocations are missing for: " + ", ".join(missing)
        )
    for config in configs:
        if config.tenant_id not in tenant_limits:
            continue
        if config.route_minimum_rate > config.route_maximum_rate:
            raise RouteAllocationConstraintError(
                f"Route {config.tenant_id}/{config.route_id} has invalid rate bounds"
            )
        if config.resource_cost_factor <= 0 or config.route_weight <= 0:
            raise RouteAllocationConstraintError(
                f"Route {config.tenant_id}/{config.route_id} must have "
                "positive weight and measured resource cost"
            )
        if not config.adaptive_enabled and not (
            config.route_minimum_rate
            <= config.current_allocation
            <= config.route_maximum_rate
        ):
            raise RouteAllocationConstraintError(
                f"Route {config.tenant_id}/{config.route_id} has a current "
                "allocation outside configured bounds"
            )

    minimum_by_tenant: dict[str, Decimal] = {}
    minimum_resource = Decimal(0)
    minimum_global = Decimal(0)
    for config in configs:
        minimum = (
            config.current_allocation
            if not config.adaptive_enabled
            else config.route_minimum_rate
        )
        minimum_by_tenant[config.tenant_id] = (
            minimum_by_tenant.get(config.tenant_id, Decimal(0)) + minimum
        )
        minimum_global += minimum
        minimum_resource += estimated_resource_usage(
            minimum,
            config.resource_cost_factor,
        )
    for tenant_id, minimum_total in minimum_by_tenant.items():
        if minimum_total > tenant_limits[tenant_id]:
            raise RouteAllocationConstraintError(
                f"Route minimums for tenant {tenant_id} exceed its "
                "tenant-wide allocation"
            )
    if minimum_global > global_capacity:
        raise RouteAllocationConstraintError(
            "Route minimum allocations exceed global service capacity"
        )
    if minimum_resource > backend_resource_budget:
        raise RouteAllocationConstraintError(
            "Route minimums exceed the backend resource budget"
        )

    if any(limit < 0 for limit in tenant_limits.values()):
        raise RouteAllocationConstraintError(
            "Tenant and global allocation limits cannot be negative"
        )
