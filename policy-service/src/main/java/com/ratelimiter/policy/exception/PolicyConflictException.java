package com.ratelimiter.policy.exception;

public class PolicyConflictException extends RuntimeException {

    public PolicyConflictException(String message) {
        super(message);
    }
}
