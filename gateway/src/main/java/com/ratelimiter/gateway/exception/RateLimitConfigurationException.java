package com.ratelimiter.gateway.exception;

public class RateLimitConfigurationException extends RuntimeException {

    public RateLimitConfigurationException(String message) {
        super(message);
    }

    public RateLimitConfigurationException(String message, Throwable cause) {
        super(message, cause);
    }
}
