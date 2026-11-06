from decimal import Decimal

from app.sla_allocation.schemas import TenantSlaConfigInput


def effective_priority_weight(config: TenantSlaConfigInput) -> Decimal:
    return config.allocation_weight * Decimal(config.priority)
