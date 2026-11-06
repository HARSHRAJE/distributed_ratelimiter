from app.sla_allocation.schemas import (
    ServiceTier,
    TenantSlaConfigInput,
)


def default_tier_policy(tier: ServiceTier) -> TenantSlaConfigInput:
    return TenantSlaConfigInput(tenant_id="_template", tier=tier)
