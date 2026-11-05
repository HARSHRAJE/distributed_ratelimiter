package com.ratelimiter.gateway.ratelimit;

import java.math.BigDecimal;

public record TokenBucketResult(
    boolean allowed,
    BigDecimal tenantRemaining,
    BigDecimal routeRemaining,
    BigDecimal globalRemaining,
    long retryAfterMillis
) {}
