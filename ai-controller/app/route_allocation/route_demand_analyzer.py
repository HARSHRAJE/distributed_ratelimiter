from decimal import Decimal

from app.route_allocation.schemas import RouteAllocationConfig


def route_demand_ceiling(config: RouteAllocationConfig) -> Decimal:
    if not config.adaptive_enabled:
        return config.current_allocation
    return max(
        config.route_minimum_rate,
        min(config.predicted_demand, config.route_maximum_rate),
    )
