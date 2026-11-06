from decimal import Decimal

from app.sla_allocation.schemas import TenantSlaConfigInput


class SlaGuaranteeError(ValueError):
    pass


def validate_guarantees(
    tenants: list[TenantSlaConfigInput],
    capacity: Decimal,
) -> None:
    if not capacity.is_finite() or capacity <= 0:
        raise SlaGuaranteeError(
            "Global service capacity must be positive and finite"
        )
    if not tenants:
        raise SlaGuaranteeError(
            "At least one tenant SLA configuration is required"
        )
    minimum_total = sum(
        (item.minimum_guaranteed_rate for item in tenants),
        Decimal(0),
    )
    if minimum_total > capacity:
        raise SlaGuaranteeError(
            "Tenant minimum guarantees exceed global service capacity"
        )
    for item in tenants:
        if item.minimum_guaranteed_rate > item.maximum_rate:
            raise SlaGuaranteeError(
                f"Tenant {item.tenant_id} minimum guarantee exceeds maximum rate"
            )
