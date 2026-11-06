from decimal import Decimal

from app.allocation.schemas import TenantAllocationConfig


class AllocationConfigurationError(ValueError):
    pass


def validate_allocation_constraints(
    tenants: list[TenantAllocationConfig],
    global_capacity: Decimal,
) -> None:
    if not global_capacity.is_finite() or global_capacity <= 0:
        raise AllocationConfigurationError(
            "Global service capacity must be a positive finite RPS value"
        )
    if not tenants:
        raise AllocationConfigurationError(
            "At least one tenant allocation configuration is required"
        )

    tenant_ids = [tenant.tenant_id for tenant in tenants]
    if len(tenant_ids) != len(set(tenant_ids)):
        raise AllocationConfigurationError(
            "Tenant allocation configuration contains duplicate tenant IDs"
        )

    minimum_total = sum(
        (
            tenant.current_allocation
            if not tenant.adaptive_enabled
            else tenant.minimum_rate
        )
        for tenant in tenants
    )
    if minimum_total > global_capacity:
        raise AllocationConfigurationError(
            "Sum of tenant minimum allocations exceeds global service capacity"
        )

    for tenant in tenants:
        if tenant.minimum_rate > tenant.maximum_rate:
            raise AllocationConfigurationError(
                f"Tenant {tenant.tenant_id} has minimum_rate above maximum_rate"
            )
        if tenant.weight <= 0 or tenant.tenant_priority < 1:
            raise AllocationConfigurationError(
                f"Tenant {tenant.tenant_id} must have positive weight and priority"
            )
        if not tenant.adaptive_enabled and not (
            tenant.minimum_rate
            <= tenant.current_allocation
            <= tenant.maximum_rate
        ):
            raise AllocationConfigurationError(
                f"Tenant {tenant.tenant_id} current allocation is outside bounds"
            )
