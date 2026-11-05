package com.ratelimiter.gateway.ratelimit;

import java.math.BigDecimal;
import java.math.RoundingMode;
import java.util.List;
import java.util.concurrent.TimeUnit;
import com.ratelimiter.gateway.exception.RateLimitConfigurationException;
import com.ratelimiter.gateway.exception.RedisUnavailableException;
import org.springframework.dao.DataAccessException;
import org.springframework.data.redis.core.ReactiveStringRedisTemplate;
import org.springframework.data.redis.core.script.RedisScript;
import org.springframework.stereotype.Service;
import io.micrometer.core.instrument.MeterRegistry;
import io.micrometer.core.instrument.Timer;
import reactor.core.publisher.Mono;

@Service
public class RedisTokenBucketService {

    private static final long TOKEN_SCALE = 1_000_000L;
    private static final BigDecimal REFILL_SCALE =
        BigDecimal.valueOf(1_000L);

    private final ReactiveStringRedisTemplate redisTemplate;
    private final RedisScript<String> tokenBucketScript;
    private final MeterRegistry meterRegistry;
    private final Timer executionTimer;
    private final Timer latencyTimer;

    public RedisTokenBucketService(
            ReactiveStringRedisTemplate redisTemplate,
            RedisScript<String> tokenBucketScript,
            MeterRegistry meterRegistry) {
        this.redisTemplate = redisTemplate;
        this.tokenBucketScript = tokenBucketScript;
        this.meterRegistry = meterRegistry;
        this.executionTimer = Timer.builder(
            "gateway.ratelimit.redis.script"
        ).description(
            "Latency of the atomic Redis token bucket script"
        ).register(meterRegistry);
        this.latencyTimer = Timer.builder("ratelimit.redis.latency")
            .description("Rate limiter Redis operation latency")
            .tag("operation", "token_bucket")
            .publishPercentileHistogram()
            .register(meterRegistry);
    }

    public Mono<TokenBucketResult> consume(TokenBucketRequest request) {
        validateHashSlot(request);
        List<String> keys = List.of(
            request.tenant().key(),
            request.route().key(),
            request.global().key()
        );
        List<String> arguments = List.of(
            capacityMicros(request.tenant()).toString(),
            refillMicrosPerMillisecond(request.tenant()).toString(),
            capacityMicros(request.route()).toString(),
            refillMicrosPerMillisecond(request.route()).toString(),
            capacityMicros(request.global()).toString(),
            refillMicrosPerMillisecond(request.global()).toString()
        );

        return Mono.defer(() -> {
            Timer.Sample sample = Timer.start(meterRegistry);
            return redisTemplate.execute(
                    tokenBucketScript,
                    keys,
                    arguments.toArray()
                )
                .single()
                .map(RedisTokenBucketService::parseResult)
                .onErrorMap(
                    DataAccessException.class,
                    exception -> new RedisUnavailableException(
                        "Redis token bucket operation failed",
                        exception
                    )
                )
                .doFinally(signal -> {
                    long elapsedNanos = sample.stop(executionTimer);
                    latencyTimer.record(elapsedNanos, TimeUnit.NANOSECONDS);
                });
        });
    }

    private static void validateHashSlot(TokenBucketRequest request) {
        String tenantSlot = hashTag(request.tenant().key());
        if (tenantSlot == null
                || !tenantSlot.equals(hashTag(request.route().key()))
                || !tenantSlot.equals(hashTag(request.global().key()))
                || request.tenant().key().equals(request.route().key())
                || request.tenant().key().equals(request.global().key())
                || request.route().key().equals(request.global().key())) {
            throw new IllegalArgumentException(
                "The three token bucket keys must be distinct and share a Redis hash tag"
            );
        }
    }

    private static String hashTag(String key) {
        if (key == null) {
            return null;
        }
        int openingBrace = key.indexOf('{');
        int closingBrace = key.indexOf('}', openingBrace + 1);
        if (openingBrace < 0 || closingBrace <= openingBrace + 1) {
            return null;
        }
        return key.substring(openingBrace + 1, closingBrace);
    }

    private static Long capacityMicros(TokenBucketRequest.Bucket bucket) {
        if (bucket.capacity() <= 0) {
            throw new IllegalArgumentException(
                "Bucket capacity must be positive"
            );
        }
        return Math.multiplyExact(bucket.capacity(), TOKEN_SCALE);
    }

    private static Long refillMicrosPerMillisecond(
            TokenBucketRequest.Bucket bucket) {
        if (bucket.refillRate() == null
                || bucket.refillRate().signum() <= 0) {
            throw new IllegalArgumentException(
                "Bucket refill rate must be positive"
            );
        }
        return bucket.refillRate()
            .setScale(3, RoundingMode.UNNECESSARY)
            .multiply(REFILL_SCALE)
            .longValueExact();
    }

    private static TokenBucketResult parseResult(String value) {
        String[] parts = value.split("\\|", -1);
        if (parts.length != 5) {
            throw new RateLimitConfigurationException(
                "Redis returned a malformed token bucket result"
            );
        }

        try {
            boolean allowed = switch (parts[0]) {
                case "1" -> true;
                case "0" -> false;
                default -> throw new IllegalArgumentException(
                    "Unexpected allowed flag"
                );
            };
            long tenant = nonNegativeLong(parts[1]);
            long route = nonNegativeLong(parts[2]);
            long global = nonNegativeLong(parts[3]);
            long retryAfterMillis = nonNegativeLong(parts[4]);
            return new TokenBucketResult(
                allowed,
                BigDecimal.valueOf(tenant, 6),
                BigDecimal.valueOf(route, 6),
                BigDecimal.valueOf(global, 6),
                retryAfterMillis
            );
        } catch (IllegalArgumentException exception) {
            throw new RateLimitConfigurationException(
                "Redis returned an invalid token bucket result",
                exception
            );
        }
    }

    private static long nonNegativeLong(String value) {
        long parsed = Long.parseLong(value);
        if (parsed < 0) {
            throw new IllegalArgumentException(
                "Token bucket result values cannot be negative"
            );
        }
        return parsed;
    }
}
