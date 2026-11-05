package com.ratelimiter.gateway.policy;

import java.time.Duration;
import java.util.concurrent.ConcurrentHashMap;
import io.micrometer.core.instrument.MeterRegistry;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;

@Component
public class PolicyCache {

    private final ConcurrentHashMap<Key, Entry> entries =
        new ConcurrentHashMap<>();
    private final long ttlNanos;
    private final MeterRegistry meterRegistry;

    public PolicyCache(
            @Value("${gateway.rate-limit.policy-cache-ttl:1s}")
            Duration ttl,
            MeterRegistry meterRegistry) {
        if (ttl.isNegative() || ttl.isZero()) {
            throw new IllegalArgumentException(
                "Policy cache TTL must be positive"
            );
        }
        ttlNanos = ttl.toNanos();
        this.meterRegistry = meterRegistry;
    }

    public PolicySnapshot get(String serviceKey, String tenantId, String routeId) {
        Key key = new Key(serviceKey, tenantId, routeId);
        Entry entry = entries.get(key);
        if (entry == null) {
            recordLookup("miss");
            return null;
        }
        if (System.nanoTime() - entry.expiresAtNanos() >= 0) {
            entries.remove(key, entry);
            recordLookup("miss");
            return null;
        }
        recordLookup("hit");
        return entry.snapshot();
    }

    public void put(PolicySnapshot snapshot) {
        entries.put(
            new Key(
                snapshot.serviceKey(),
                snapshot.tenantId(),
                snapshot.routeId()
            ),
            new Entry(snapshot, System.nanoTime() + ttlNanos)
        );
    }

    public void invalidate(String serviceKey, String tenantId, String routeId) {
        entries.remove(new Key(serviceKey, tenantId, routeId));
    }

    private void recordLookup(String outcome) {
        meterRegistry.counter(
            "ratelimit.policy.cache",
            "outcome",
            outcome
        ).increment();
    }

    private record Key(String serviceKey, String tenantId, String routeId) {}

    private record Entry(PolicySnapshot snapshot, long expiresAtNanos) {}
}
