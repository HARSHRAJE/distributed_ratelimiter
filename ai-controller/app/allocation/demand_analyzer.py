from decimal import Decimal

from app.allocation.schemas import TenantAllocationConfig


def demand_ceiling(tenant: TenantAllocationConfig) -> Decimal:
    if not tenant.adaptive_enabled:
        return tenant.current_allocation
    return max(
        tenant.minimum_rate,
        min(tenant.predicted_demand, tenant.maximum_rate),
    )
