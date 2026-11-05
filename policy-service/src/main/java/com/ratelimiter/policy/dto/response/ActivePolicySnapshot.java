package com.ratelimiter.policy.dto.response;

import java.math.BigDecimal;
import java.util.UUID;

public record ActivePolicySnapshot(
    String serviceKey,
    UUID policyId,
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
    String source
) {}
