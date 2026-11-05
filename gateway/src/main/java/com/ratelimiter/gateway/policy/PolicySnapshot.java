package com.ratelimiter.gateway.policy;

import java.math.BigDecimal;

public record PolicySnapshot(
    String serviceKey,
    String policyId,
    String tenantId,
    String routeId,
    String status,
    Long syncRevision,
    Long activeVersion,
    Integer tenantCapacity,
    BigDecimal tenantRefillRate,
    Integer routeCapacity,
    BigDecimal routeRefillRate,
    BigDecimal minRefillRate,
    BigDecimal maxRefillRate,
    String source,
    Long configVersion,
    Integer globalCapacity,
    BigDecimal globalRefillRate,
    BigDecimal hardMaxRefillRate
) {
    public boolean active() {
        return "ACTIVE".equals(status);
    }
}
