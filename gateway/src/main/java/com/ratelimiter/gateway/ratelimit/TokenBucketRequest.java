package com.ratelimiter.gateway.ratelimit;

import java.math.BigDecimal;

public record TokenBucketRequest(
    Bucket tenant,
    Bucket route,
    Bucket global
) {
    public record Bucket(
        String key,
        long capacity,
        BigDecimal refillRate
    ) {}
}
