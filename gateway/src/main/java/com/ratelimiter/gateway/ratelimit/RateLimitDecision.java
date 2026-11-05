package com.ratelimiter.gateway.ratelimit;

public record RateLimitDecision(
    Outcome outcome,
    TokenBucketResult bucketResult
) {
    public enum Outcome {
        ALLOWED,
        RATE_LIMITED,
        POLICY_DISABLED
    }

    public static RateLimitDecision from(TokenBucketResult result) {
        return new RateLimitDecision(
            result.allowed() ? Outcome.ALLOWED : Outcome.RATE_LIMITED,
            result
        );
    }
}
