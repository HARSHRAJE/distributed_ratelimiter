package com.ratelimiter.gateway.policy;

import com.ratelimiter.gateway.exception.RateLimitConfigurationException;
import com.ratelimiter.gateway.exception.RedisUnavailableException;
import java.math.BigDecimal;
import java.util.UUID;
import io.micrometer.core.instrument.MeterRegistry;
import io.micrometer.core.instrument.Timer;
import org.springframework.dao.DataAccessException;
import org.springframework.data.redis.core.ReactiveStringRedisTemplate;
import org.springframework.stereotype.Service;
import reactor.core.publisher.Mono;
import tools.jackson.core.JacksonException;
import tools.jackson.databind.ObjectMapper;

@Service
public class PolicyResolver {

    private static final String SERVICE_KEY_PATTERN =
        "[A-Za-z0-9._-]{1,100}";
    private static final String SEGMENT_PATTERN =
        "[A-Za-z0-9._-]{1,128}";

    private final ReactiveStringRedisTemplate redisTemplate;
    private final ObjectMapper objectMapper;
    private final PolicyCache cache;
    private final MeterRegistry meterRegistry;

    public PolicyResolver(
            ReactiveStringRedisTemplate redisTemplate,
            ObjectMapper objectMapper,
            PolicyCache cache,
            MeterRegistry meterRegistry) {
        this.redisTemplate = redisTemplate;
        this.objectMapper = objectMapper;
        this.cache = cache;
        this.meterRegistry = meterRegistry;
    }

    public Mono<PolicySnapshot> resolve(
            String serviceKey,
            String tenantId,
            String routeId) {
        validateKeySegment(serviceKey, SERVICE_KEY_PATTERN, "service key");
        validateUuid(tenantId);
        validateKeySegment(routeId, SEGMENT_PATTERN, "route ID");

        Timer.Sample sample = Timer.start(meterRegistry);
        PolicySnapshot cached = cache.get(serviceKey, tenantId, routeId);
        if (cached != null) {
            return Mono.just(cached).doFinally(signal ->
                recordLookupDuration(sample)
            );
        }

        String serviceTag = "{" + serviceKey + "}";
        String indexKey = "rl:policy-index:" + serviceTag;
        String serviceConfigKey = "rl:service-config:" + serviceTag;

        Mono<PolicyPart> policy = redisTemplate.opsForHash()
            .get(indexKey, tenantId + "|" + routeId)
            .switchIfEmpty(Mono.error(new RateLimitConfigurationException(
                "No rate-limit policy is configured for this tenant and route"
            )))
            .map(Object::toString)
            .flatMap(policyId -> {
                validateUuid(policyId);
                String policyKey =
                    "rl:policy:" + serviceTag + ":" + policyId;
                return redisTemplate.opsForValue()
                    .get(policyKey)
                    .switchIfEmpty(Mono.error(
                        new RateLimitConfigurationException(
                            "The indexed rate-limit policy snapshot is missing"
                        )
                    ))
                    .map(payload -> readSnapshot(
                        payload,
                        PolicyPart.class,
                        "policy"
                    ))
                    .map(snapshot -> validatePolicy(
                        snapshot,
                        policyId,
                        serviceKey,
                        tenantId,
                        routeId
                    ));
            });

        Mono<ServicePart> service = redisTemplate.opsForValue()
            .get(serviceConfigKey)
            .switchIfEmpty(Mono.error(new RateLimitConfigurationException(
                "Global service rate-limit configuration is missing"
            )))
            .map(payload -> readSnapshot(
                payload,
                ServicePart.class,
                "service configuration"
            ))
            .map(snapshot -> validateService(snapshot, serviceKey));

        return Mono.zip(policy, service)
            .map(config -> combine(
                config.getT1(),
                config.getT2()
            ))
            .doOnNext(snapshot -> {
                if (!cache.put(snapshot)) {
                    throw new RateLimitConfigurationException(
                        "Redis returned a stale policy snapshot"
                    );
                }
            })
            .onErrorMap(
                DataAccessException.class,
                exception -> new RedisUnavailableException(
                    "Redis rate-limit configuration lookup failed",
                    exception
                )
            )
            .doFinally(signal -> recordLookupDuration(sample));
    }

    private void recordLookupDuration(Timer.Sample sample) {
        sample.stop(Timer.builder("ratelimit.policy.lookup")
            .description("Rate-limit policy resolution duration")
            .publishPercentileHistogram()
            .register(meterRegistry));
    }

    private <T> T readSnapshot(
            String payload,
            Class<T> snapshotType,
            String description) {
        try {
            return objectMapper.readValue(payload, snapshotType);
        } catch (JacksonException exception) {
            throw new RateLimitConfigurationException(
                "Redis contains an invalid " + description + " snapshot",
                exception
            );
        }
    }

    private PolicyPart validatePolicy(
            PolicyPart snapshot,
            String policyId,
            String serviceKey,
            String tenantId,
            String routeId) {
        if (snapshot == null
                || !policyId.equals(snapshot.policyId())
                || !serviceKey.equals(snapshot.serviceKey())
                || !tenantId.equals(snapshot.tenantId())
                || !routeId.equals(snapshot.routeId())
                || snapshot.syncRevision() == null
                || snapshot.syncRevision() <= 0
                || snapshot.activeVersion() == null
                || snapshot.activeVersion() <= 0
                || snapshot.tenantCapacity() == null
                || snapshot.tenantCapacity() <= 0
                || snapshot.routeCapacity() == null
                || snapshot.routeCapacity() <= 0
                || !positive(snapshot.tenantRefillRate())
                || !positive(snapshot.routeRefillRate())
                || !positive(snapshot.minRefillRate())
                || !positive(snapshot.maxRefillRate())
                || snapshot.source() == null
                || !snapshot.source().matches(SEGMENT_PATTERN)
                || !("ACTIVE".equals(snapshot.status())
                    || "DISABLED".equals(snapshot.status()))) {
            throw new RateLimitConfigurationException(
                "Redis contains an incomplete or inconsistent policy snapshot"
            );
        }
        if (snapshot.routeRefillRate().compareTo(snapshot.minRefillRate()) < 0
                || snapshot.routeRefillRate()
                    .compareTo(snapshot.maxRefillRate()) > 0) {
            throw new RateLimitConfigurationException(
                "Redis policy refill rate is outside its configured bounds"
            );
        }
        return snapshot;
    }

    private ServicePart validateService(
            ServicePart snapshot,
            String serviceKey) {
        if (snapshot == null
                || !serviceKey.equals(snapshot.serviceKey())
                || snapshot.configVersion() == null
                || snapshot.configVersion() <= 0
                || snapshot.globalCapacity() == null
                || snapshot.globalCapacity() <= 0
                || !positive(snapshot.globalRefillRate())
                || !positive(snapshot.hardMaxRefillRate())
                || snapshot.globalRefillRate()
                    .compareTo(snapshot.hardMaxRefillRate()) > 0) {
            throw new RateLimitConfigurationException(
                "Redis contains an incomplete or inconsistent service configuration"
            );
        }
        return snapshot;
    }

    private PolicySnapshot combine(
            PolicyPart policy,
            ServicePart service) {
        if (policy.tenantRefillRate()
                    .compareTo(service.hardMaxRefillRate()) > 0
                || policy.routeRefillRate()
                    .compareTo(service.hardMaxRefillRate()) > 0
                || policy.maxRefillRate()
                    .compareTo(service.hardMaxRefillRate()) > 0) {
            throw new RateLimitConfigurationException(
                "Redis policy refill rates exceed the service hard maximum"
            );
        }
        return new PolicySnapshot(
            policy.serviceKey(),
            policy.policyId(),
            policy.tenantId(),
            policy.routeId(),
            policy.status(),
            policy.syncRevision(),
            policy.activeVersion(),
            policy.tenantCapacity(),
            policy.tenantRefillRate(),
            policy.routeCapacity(),
            policy.routeRefillRate(),
            policy.minRefillRate(),
            policy.maxRefillRate(),
            policy.source(),
            service.configVersion(),
            service.globalCapacity(),
            service.globalRefillRate(),
            service.hardMaxRefillRate()
        );
    }

    private static boolean positive(BigDecimal value) {
        return value != null && value.signum() > 0 && value.scale() <= 3;
    }

    private static void validateKeySegment(
            String value,
            String pattern,
            String description) {
        if (value == null || !value.matches(pattern)) {
            throw new RateLimitConfigurationException(
                "Invalid " + description + " in rate-limit configuration"
            );
        }
    }

    private static void validateUuid(String value) {
        try {
            UUID.fromString(value);
        } catch (IllegalArgumentException | NullPointerException exception) {
            throw new RateLimitConfigurationException(
                "Invalid tenant or policy ID in rate-limit configuration",
                exception
            );
        }
    }

    private record PolicyPart(
        String serviceKey,
        String policyId,
        String tenantId,
        String routeId,
        String status,
        Long syncRevision,
        Long activeVersion,
        Integer tenantCapacity,
        BigDecimal tenantRefillRate,
        Integer routeCapacity,
        BigDecimal routeRefillRate,
        BigDecimal minRefillRate,
        BigDecimal maxRefillRate,
        String source
    ) {}

    private record ServicePart(
        String serviceKey,
        Long configVersion,
        Integer globalCapacity,
        BigDecimal globalRefillRate,
        BigDecimal hardMaxRefillRate
    ) {}
}
