package com.ratelimiter.gateway.ratelimit;

import com.ratelimiter.gateway.policy.PolicySnapshot;
import org.springframework.stereotype.Service;
import reactor.core.publisher.Mono;

@Service
public class RateLimitService {

    private final RedisTokenBucketService tokenBucketService;

    public RateLimitService(RedisTokenBucketService tokenBucketService) {
        this.tokenBucketService = tokenBucketService;
    }

    public Mono<RateLimitDecision> evaluate(PolicySnapshot snapshot) {
        if (!snapshot.active()) {
            return Mono.just(new RateLimitDecision(
                RateLimitDecision.Outcome.POLICY_DISABLED,
                null
            ));
        }

        String serviceTag = "{" + snapshot.serviceKey() + "}";
        TokenBucketRequest request = new TokenBucketRequest(
            new TokenBucketRequest.Bucket(
                "rl:bucket:" + serviceTag + ":tenant:" + snapshot.tenantId(),
                snapshot.tenantCapacity(),
                snapshot.tenantRefillRate()
            ),
            new TokenBucketRequest.Bucket(
                "rl:bucket:" + serviceTag + ":route:"
                    + snapshot.tenantId() + ":" + snapshot.routeId(),
                snapshot.routeCapacity(),
                snapshot.routeRefillRate()
            ),
            new TokenBucketRequest.Bucket(
                "rl:bucket:" + serviceTag + ":global",
                snapshot.globalCapacity(),
                snapshot.globalRefillRate()
            )
        );
        return tokenBucketService.consume(request)
            .map(RateLimitDecision::from);
    }
}
