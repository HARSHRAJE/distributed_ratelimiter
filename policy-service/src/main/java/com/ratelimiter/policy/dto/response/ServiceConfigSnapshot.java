package com.ratelimiter.policy.dto.response;

import java.math.BigDecimal;

public record ServiceConfigSnapshot(
    String serviceKey,
    Long configVersion,
    Integer globalCapacity,
    BigDecimal globalRefillRate,
    BigDecimal hardMaxRefillRate
) {}
