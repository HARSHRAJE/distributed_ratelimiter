package com.ratelimiter.policy.dto.response;

import java.math.BigDecimal;
import java.time.Instant;

public record PolicyVersionResponse(
    Long version,
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