package com.ratelimiter.policy.dto.response;

import java.math.BigDecimal;
import java.time.Instant;
import java.util.UUID;

public record PolicyResponse(
    UUID policyId,
    String serviceKey,
    String tenantId,
    String routeId,
    Long activeVersion,
    String status,
    Integer tenantCapacity,
    BigDecimal tenantRefillRate,
    Integer routeCapacity,
    BigDecimal routeRefillRate,
    BigDecimal minRefillRate,
    BigDecimal maxRefillRate,
    String source,
    String createdBy,
    Instant createdAt
) {}