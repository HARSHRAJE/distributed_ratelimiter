package com.ratelimiter.gateway.ratelimit;

import io.micrometer.core.instrument.MeterRegistry;
import org.springframework.stereotype.Component;

@Component
public class RateLimitMetrics {

    private final MeterRegistry registry;

    public RateLimitMetrics(MeterRegistry registry) {
        this.registry = registry;
    }

    public void recordAllowed(String service) {
        registry.counter(
            "ratelimit.requests",
            "service", service,
            "outcome", "allowed"
        ).increment();
    }

    public void recordRejected(String service, String limitType) {
        registry.counter(
            "ratelimit.requests",
            "service", service,
            "outcome", "rejected",
            "limit_type", limitType
        ).increment();
    }
}
