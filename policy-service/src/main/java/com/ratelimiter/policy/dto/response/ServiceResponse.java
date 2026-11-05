package com.ratelimiter.policy.dto.response;

import java.math.BigDecimal;
import java.time.Instant;
import java.util.UUID;

public record ServiceResponse(
    UUID id,
    String serviceKey,
    Long configVersion,
    Integer globalCapacity,
    BigDecimal globalRefillRate,
    BigDecimal hardMaxRefillRate,
    Boolean adaptiveEnabled,
    Instant createdAt,
    Instant updatedAt
) {}