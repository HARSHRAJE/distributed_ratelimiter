package com.ratelimiter.gateway.policy;

import java.time.Duration;
import java.util.Comparator;
import java.util.concurrent.ConcurrentHashMap;
import io.micrometer.core.instrument.Gauge;
import io.micrometer.core.instrument.MeterRegistry;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;

@Component
public class PolicyCache {

    private final ConcurrentHashMap<Key, Entry> entries =
        new ConcurrentHashMap<>();
    private final long ttlNanos;
    private final int maximumEntries;
    private final MeterRegistry meterRegistry;

    @Autowired
    public PolicyCache(
            @Value("${gateway.rate-limit.policy-cache-ttl:1s}")
            Duration ttl,
            @Value("${gateway.rate-limit.policy-cache-max-entries:100000}")
            int maximumEntries,
            MeterRegistry meterRegistry) {
        if (ttl.isNegative() || ttl.isZero()) {
            throw new IllegalArgumentException(
                "Policy cache TTL must be positive"
            );
        }
        if (maximumEntries < 1) {
            throw new IllegalArgumentException(
                "Policy cache maximum entries must be positive"
            );
        }
        ttlNanos = ttl.toNanos();
        this.maximumEntries = maximumEntries;
        this.meterRegistry = meterRegistry;
        Gauge.builder(
            "ratelimit.policy.cache.size",
            entries,
            ConcurrentHashMap::mappingCount
        ).register(meterRegistry);
        Gauge.builder(
            "ratelimit.policy.cache.maximum",
            this,
            cache -> cache.maximumEntries
        ).register(meterRegistry);
        Gauge.builder(
            "ratelimit.policy.cache.oldest_age_seconds",
            this,
            PolicyCache::oldestEntryAgeSeconds
        ).register(meterRegistry);
    }

    public PolicyCache(Duration ttl, MeterRegistry meterRegistry) {
        this(ttl, 100_000, meterRegistry);
    }

    public PolicySnapshot get(String serviceKey, String tenantId, String routeId) {
        Key key = new Key(serviceKey, tenantId, routeId);
        Entry entry = entries.get(key);
        if (entry == null) {
            recordLookup("miss");
            return null;
        }
        if (System.nanoTime() - entry.expiresAtNanos() >= 0) {
            recordLookup("miss");
            meterRegistry.counter("ratelimit.policy.cache.expired")
                .increment();
            return null;
        }
        recordLookup("hit");
        return entry.snapshot();
    }

    public synchronized boolean put(PolicySnapshot snapshot) {
        Key key = new Key(
            snapshot.serviceKey(),
            snapshot.tenantId(),
            snapshot.routeId()
        );
        long now = System.nanoTime();
        Entry current = entries.get(key);
        if (current != null && isOlder(snapshot, current.snapshot())) {
            meterRegistry.counter("ratelimit.policy.cache.stale_update")
                .increment();
            return false;
        }
        if (current == null && entries.size() >= maximumEntries) {
            entries.entrySet().removeIf(
                item -> now - item.getValue().expiresAtNanos() >= 0
            );
            if (entries.size() >= maximumEntries) {
                entries.entrySet().stream()
                    .min(Comparator.comparingLong(
                        item -> item.getValue().insertedAtNanos()
                    ))
                    .ifPresent(item -> entries.remove(item.getKey(), item.getValue()));
                meterRegistry.counter("ratelimit.policy.cache.evictions")
                    .increment();
            }
        }
        entries.put(key, new Entry(
            snapshot,
            now + ttlNanos,
            now
        ));
        return true;
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

    private static boolean isOlder(
            PolicySnapshot incoming,
            PolicySnapshot existing) {
        boolean older = incoming.syncRevision() < existing.syncRevision()
            || incoming.activeVersion() < existing.activeVersion()
            || incoming.configVersion() < existing.configVersion();
        boolean sameVersion = incoming.syncRevision()
                .equals(existing.syncRevision())
            && incoming.activeVersion().equals(existing.activeVersion())
            && incoming.configVersion().equals(existing.configVersion());
        return older || (sameVersion && !incoming.equals(existing));
    }

    private double oldestEntryAgeSeconds() {
        long now = System.nanoTime();
        return entries.values().stream()
            .mapToLong(Entry::insertedAtNanos)
            .min()
            .stream()
            .mapToDouble(insertedAt ->
                Math.max(0L, now - insertedAt) / 1_000_000_000.0
            )
            .findFirst()
            .orElse(0.0);
    }

    private record Key(String serviceKey, String tenantId, String routeId) {}

    private record Entry(
        PolicySnapshot snapshot,
        long expiresAtNanos,
        long insertedAtNanos
    ) {}
}
