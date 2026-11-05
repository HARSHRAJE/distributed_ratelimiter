package com.ratelimiter.gateway.policy;

import static org.assertj.core.api.Assertions.assertThat;

import java.math.BigDecimal;
import java.time.Duration;
import io.micrometer.core.instrument.MeterRegistry;
import io.micrometer.core.instrument.simple.SimpleMeterRegistry;
import org.junit.jupiter.api.Test;

class PolicyCacheTests {

    @Test
    void expiresPolicySnapshotsAfterConfiguredTtl() throws InterruptedException {
        MeterRegistry registry = new SimpleMeterRegistry();
        PolicyCache cache = new PolicyCache(
            Duration.ofMillis(1),
            registry
        );
        PolicySnapshot snapshot = new PolicySnapshot(
            "orders-service",
            "policy-id",
            "tenant-id",
            "get-orders",
            "ACTIVE",
            1L,
            1L,
            10,
            BigDecimal.ONE,
            5,
            BigDecimal.ONE,
            BigDecimal.ONE,
            BigDecimal.ONE,
            "MANUAL",
            1L,
            100,
            BigDecimal.ONE,
            BigDecimal.TEN
        );

        cache.put(snapshot);
        assertThat(cache.get(
            "orders-service",
            "tenant-id",
            "get-orders"
        )).isSameAs(snapshot);
        assertThat(registry.get("ratelimit.policy.cache")
            .tag("outcome", "hit")
            .counter()
            .count()).isEqualTo(1);

        Thread.sleep(5);

        assertThat(cache.get(
            "orders-service",
            "tenant-id",
            "get-orders"
        )).isNull();
        assertThat(registry.get("ratelimit.policy.cache")
            .tag("outcome", "miss")
            .counter()
            .count()).isEqualTo(1);
    }
}
