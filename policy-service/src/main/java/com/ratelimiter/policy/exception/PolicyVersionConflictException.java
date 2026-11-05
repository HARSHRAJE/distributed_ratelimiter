package com.ratelimiter.policy.exception;

public class PolicyVersionConflictException extends RuntimeException {

    public PolicyVersionConflictException(String message) {
        super(message);
    }
}
