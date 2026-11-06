package com.ratelimiter.gateway.ratelimit;

import static org.assertj.core.api.Assertions.assertThat;
import static org.junit.jupiter.api.Assumptions.assumeTrue;

import java.math.BigDecimal;
import java.time.Duration;
import java.util.ArrayList;
import java.util.List;
import java.util.UUID;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.data.redis.connection.lettuce.LettuceConnectionFactory;
import org.springframework.data.redis.core.ReactiveStringRedisTemplate;
import org.springframework.data.redis.core.script.DefaultRedisScript;
import org.springframework.data.redis.core.script.RedisScript;
import org.springframework.core.io.ClassPathResource;
import io.micrometer.core.instrument.simple.SimpleMeterRegistry;
import com.ratelimiter.gateway.policy.PolicyCache;
import com.ratelimiter.gateway.policy.PolicyResolver;
import com.ratelimiter.gateway.policy.PolicySnapshot;
import tools.jackson.databind.json.JsonMapper;
import reactor.core.publisher.Flux;

class RedisTokenBucketServiceTests {

    private LettuceConnectionFactory connectionFactory;
    private ReactiveStringRedisTemplate redisTemplate;
    private RedisTokenBucketService service;
    private final List<String> testKeys = new ArrayList<>();

    @BeforeEach
    void setUp() {
        connectionFactory = new LettuceConnectionFactory("localhost", 6379);
        connectionFactory.afterPropertiesSet();
        redisTemplate = new ReactiveStringRedisTemplate(connectionFactory);

        try {
            redisTemplate.getConnectionFactory()
                .getReactiveConnection()
                .ping()
                .block(Duration.ofSeconds(2));
        } catch (RuntimeException exception) {
            assumeTrue(false, "Local Redis is required for token bucket integration tests");
        }

        DefaultRedisScript<String> script = new DefaultRedisScript<>();
        script.setLocation(new ClassPathResource("redis/token_bucket.lua"));
        script.setResultType(String.class);
        RedisScript<String> redisScript = script;
        service = new RedisTokenBucketService(
            redisTemplate,
            redisScript,
            new SimpleMeterRegistry()
        );
    }

    @AfterEach
    void tearDown() {
        if (redisTemplate != null && !testKeys.isEmpty()) {
            redisTemplate.delete(testKeys.toArray(String[]::new))
                .block(Duration.ofSeconds(2));
            testKeys.clear();
        }
        if (connectionFactory != null) {
            connectionFactory.destroy();
        }
    }

    @Test
    void allowsWhenAllBucketsHaveTokensThenRejectsWhenOneIsEmpty() {
        TokenBucketRequest request = request(1, 0.001, 2, 0.001, 3, 0.001);

        TokenBucketResult first = service.consume(request).block();
        TokenBucketResult second = service.consume(request).block();

        assertThat(first).isNotNull();
        assertThat(first.allowed()).isTrue();
        assertThat(first.tenantRemaining()).isEqualByComparingTo("0");
        assertThat(second).isNotNull();
        assertThat(second.allowed()).isFalse();
        assertThat(second.retryAfterMillis()).isPositive();
        assertThat(second.routeRemaining())
            .isBetween(new BigDecimal("1"), new BigDecimal("2"));
        assertThat(second.globalRemaining())
            .isBetween(new BigDecimal("2"), new BigDecimal("3"));

        delete(request);
    }

    @Test
    void rejectionDoesNotDeductFromBucketsThatHaveTokens() {
        TokenBucketRequest request = request(2, 1, 2, 1, 2, 1);
        String routeKey = request.route().key();
        redisTemplate.opsForHash()
            .putAll(routeKey, java.util.Map.of(
                "tokens", "0",
                "last_refill_ms", Long.toString(System.currentTimeMillis())
            ))
            .block(Duration.ofSeconds(2));

        TokenBucketResult result = service.consume(request)
            .block(Duration.ofSeconds(2));

        assertThat(result).isNotNull();
        assertThat(result.allowed()).isFalse();
        assertThat(result.tenantRemaining()).isEqualByComparingTo("2");
        assertThat(result.globalRemaining()).isEqualByComparingTo("2");

        delete(request);
    }

    @Test
    void emptyGlobalBucketRejectsWithoutDeductingOtherBuckets() {
        TokenBucketRequest request = request(2, 1, 2, 1, 2, 1);
        redisTemplate.opsForHash()
            .putAll(request.global().key(), java.util.Map.of(
                "tokens", "0",
                "last_refill_ms", Long.toString(System.currentTimeMillis())
            ))
            .block(Duration.ofSeconds(2));

        TokenBucketResult result = service.consume(request)
            .block(Duration.ofSeconds(2));

        assertThat(result).isNotNull();
        assertThat(result.allowed()).isFalse();
        assertThat(result.tenantRemaining()).isBetween(
            new BigDecimal("2"),
            new BigDecimal("2.001")
        );
        assertThat(result.routeRemaining()).isBetween(
            new BigDecimal("2"),
            new BigDecimal("2.001")
        );

        delete(request);
    }

    @Test
    void refillsOverTimeAndDoesNotExceedCapacity() throws InterruptedException {
        TokenBucketRequest request = request(1, 1, 1, 1, 1, 1);
        assertThat(service.consume(request).block().allowed()).isTrue();
        Thread.sleep(1100);

        TokenBucketResult afterRefill = service.consume(request)
            .block(Duration.ofSeconds(2));

        assertThat(afterRefill).isNotNull();
        assertThat(afterRefill.allowed()).isTrue();
        TokenBucketResult immediatelyAfter = service.consume(request)
            .block(Duration.ofSeconds(2));
        assertThat(immediatelyAfter).isNotNull();
        assertThat(immediatelyAfter.allowed()).isFalse();

        delete(request);
    }

    @Test
    void expiresIdleBucketAfterTheRefillHorizon() throws InterruptedException {
        TokenBucketRequest request = request(1, 10, 1, 10, 1, 10);

        service.consume(request).block(Duration.ofSeconds(2));

        assertThat(redisTemplate.hasKey(request.tenant().key())
            .block(Duration.ofSeconds(2))).isTrue();
        Thread.sleep(150);
        assertThat(redisTemplate.hasKey(request.tenant().key())
            .block(Duration.ofSeconds(2))).isFalse();

        delete(request);
    }

    @Test
    void concurrentCallsNeverOverspendAnyBucket() {
        TokenBucketRequest request = request(10, 0.001, 10, 0.001, 10, 0.001);

        List<TokenBucketResult> results = Flux.range(0, 100)
            .flatMap(ignored -> service.consume(request), 100)
            .collectList()
            .block(Duration.ofSeconds(30));

        assertThat(results).isNotNull();
        assertThat(results.stream().filter(TokenBucketResult::allowed))
            .hasSize(10);

        delete(request);
    }

    @Test
    void resolvesPolicyAndServiceSnapshotsIntoSharedSlotKeys() {
        String serviceKey = "orders-service-test";
        String tenantId = "0795a60c-05af-4ad3-b220-7cc572362aa1";
        String policyId = UUID.randomUUID().toString();
        String routeId = "get-orders";
        String serviceTag = "{" + serviceKey + "}";
        String indexKey = "rl:policy-index:" + serviceTag;
        String policyKey = "rl:policy:" + serviceTag + ":" + policyId;
        String serviceConfigKey = "rl:service-config:" + serviceTag;
        testKeys.add(indexKey);
        testKeys.add(policyKey);
        testKeys.add(serviceConfigKey);
        redisTemplate.opsForHash()
            .put(indexKey, tenantId + "|" + routeId, policyId)
            .block(Duration.ofSeconds(2));
        redisTemplate.opsForValue().set(policyKey, """
            {
              "serviceKey": "orders-service-test",
              "policyId": "%s",
              "tenantId": "%s",
              "routeId": "get-orders",
              "status": "ACTIVE",
              "syncRevision": 4,
              "activeVersion": 3,
              "tenantCapacity": 500,
              "tenantRefillRate": 100.000,
              "routeCapacity": 100,
              "routeRefillRate": 20.000,
              "minRefillRate": 5.000,
              "maxRefillRate": 100.000,
              "source": "MANUAL"
            }
            """.formatted(policyId, tenantId)).block(Duration.ofSeconds(2));
        redisTemplate.opsForValue().set(serviceConfigKey, """
            {
              "serviceKey": "orders-service-test",
              "configVersion": 2,
              "globalCapacity": 1000,
              "globalRefillRate": 200.000,
              "hardMaxRefillRate": 500.000
            }
            """).block(Duration.ofSeconds(2));

        PolicyResolver policyResolver =
            new PolicyResolver(
                redisTemplate,
                JsonMapper.builder().build(),
                new PolicyCache(
                    Duration.ofSeconds(1),
                    new SimpleMeterRegistry()
                ),
                new SimpleMeterRegistry()
            );
        PolicySnapshot resolved = policyResolver.resolve(
            serviceKey,
            tenantId,
            routeId
        ).block(Duration.ofSeconds(2));

        assertThat(resolved).isNotNull();
        assertThat(resolved.active()).isTrue();
        assertThat(resolved.tenantCapacity()).isEqualTo(500);
        assertThat(resolved.globalCapacity()).isEqualTo(1000);
        assertThat(resolved.routeId()).isEqualTo(routeId);
        assertThat(policyResolver.resolve(
            serviceKey,
            tenantId,
            routeId
        ).block(Duration.ofSeconds(2))).isSameAs(resolved);
    }

    private TokenBucketRequest request(
            int tenantCapacity,
            double tenantRate,
            int routeCapacity,
            double routeRate,
            int globalCapacity,
            double globalRate) {
        String prefix = "rl:test:bucket:{" + UUID.randomUUID() + "}";
        TokenBucketRequest request = new TokenBucketRequest(
            bucket(prefix + ":tenant", tenantCapacity, tenantRate),
            bucket(prefix + ":route", routeCapacity, routeRate),
            bucket(prefix + ":global", globalCapacity, globalRate)
        );
        testKeys.add(request.tenant().key());
        testKeys.add(request.route().key());
        testKeys.add(request.global().key());
        return request;
    }

    private TokenBucketRequest.Bucket bucket(
            String key,
            int capacity,
            double refillRate) {
        return new TokenBucketRequest.Bucket(
            key,
            capacity,
            BigDecimal.valueOf(refillRate)
        );
    }

    private void delete(TokenBucketRequest request) {
        redisTemplate.delete(
            request.tenant().key(),
            request.route().key(),
            request.global().key()
        ).block(Duration.ofSeconds(2));
    }
}
