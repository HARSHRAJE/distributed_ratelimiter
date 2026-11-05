package com.ratelimiter.auth.exception;

public class InvalidTokenException extends RuntimeException {

    public InvalidTokenException() {
        super("The refresh token is invalid or expired");
    }
}
