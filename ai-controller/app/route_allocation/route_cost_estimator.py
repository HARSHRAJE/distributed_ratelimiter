from decimal import Decimal

from app.route_allocation.schemas import RouteAllocationConfig


def effective_route_weight(config: RouteAllocationConfig) -> Decimal:
    """Weight per resource unit; cost must come from measured backend usage."""
    return (
        config.route_weight
        * Decimal(config.priority)
        / config.resource_cost_factor
    )


def estimated_resource_usage(
    allocated_rate: Decimal,
    resource_cost_factor: Decimal,
) -> Decimal:
    return allocated_rate * resource_cost_factor
