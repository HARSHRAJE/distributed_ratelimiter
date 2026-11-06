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
            Duration.ofMillis(100),
            registry
        );
        PolicySnapshot snapshot = policy(1, 1, 1);

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

        Thread.sleep(150);

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

    @Test
    void doesNotReplaceNewerPolicyWithStaleSnapshot() {
        MeterRegistry registry = new SimpleMeterRegistry();
        PolicyCache cache = new PolicyCache(
            Duration.ofSeconds(1),
            1,
            registry
        );
        PolicySnapshot newer = policy(3, 3, 3);
        PolicySnapshot stale = policy(2, 2, 2);
        PolicySnapshot duplicateVersionWithDifferentState = new PolicySnapshot(
            newer.serviceKey(),
            newer.policyId(),
            newer.tenantId(),
            newer.routeId(),
            "DISABLED",
            newer.syncRevision(),
            newer.activeVersion(),
            newer.tenantCapacity(),
            newer.tenantRefillRate(),
            newer.routeCapacity(),
            newer.routeRefillRate(),
            newer.minRefillRate(),
            newer.maxRefillRate(),
            newer.source(),
            newer.configVersion(),
            newer.globalCapacity(),
            newer.globalRefillRate(),
            newer.hardMaxRefillRate()
        );

        assertThat(cache.put(newer)).isTrue();
        assertThat(cache.put(stale)).isFalse();
        assertThat(cache.put(duplicateVersionWithDifferentState)).isFalse();
        assertThat(cache.get(
            "orders-service",
            "tenant-id",
            "get-orders"
        )).isSameAs(newer);
        assertThat(registry.get("ratelimit.policy.cache.stale_update")
            .counter()
            .count()).isEqualTo(2);
        assertThat(registry.get("ratelimit.policy.cache.size")
            .gauge()
            .value()).isEqualTo(1);
    }

    @Test
    void evictsOldestSnapshotWhenCacheReachesConfiguredBound() {
        PolicyCache cache = new PolicyCache(
            Duration.ofSeconds(1),
            1,
            new SimpleMeterRegistry()
        );
        PolicySnapshot first = policy(1, 1, 1);
        PolicySnapshot second = new PolicySnapshot(
            first.serviceKey(),
            first.policyId(),
            first.tenantId(),
            "create-order",
            first.status(),
            first.syncRevision(),
            first.activeVersion(),
            first.tenantCapacity(),
            first.tenantRefillRate(),
            first.routeCapacity(),
            first.routeRefillRate(),
            first.minRefillRate(),
            first.maxRefillRate(),
            first.source(),
            first.configVersion(),
            first.globalCapacity(),
            first.globalRefillRate(),
            first.hardMaxRefillRate()
        );

        cache.put(first);
        cache.put(second);

        assertThat(cache.get(
            first.serviceKey(),
            first.tenantId(),
            first.routeId()
        )).isNull();
        assertThat(cache.get(
            second.serviceKey(),
            second.tenantId(),
            second.routeId()
        )).isSameAs(second);
    }

    private static PolicySnapshot policy(
            long syncRevision,
            long activeVersion,
            long configVersion) {
        return new PolicySnapshot(
            "orders-service",
            "policy-id",
            "tenant-id",
            "get-orders",
            "ACTIVE",
            syncRevision,
            activeVersion,
            10,
            BigDecimal.ONE,
            5,
            BigDecimal.ONE,
            BigDecimal.ONE,
            BigDecimal.ONE,
            "MANUAL",
            configVersion,
            100,
            BigDecimal.ONE,
            BigDecimal.TEN
        );
    }
}
