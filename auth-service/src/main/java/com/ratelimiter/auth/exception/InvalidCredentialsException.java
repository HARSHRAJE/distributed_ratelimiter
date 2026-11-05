package com.ratelimiter.auth.exception;

public class InvalidCredentialsException extends RuntimeException {

    public InvalidCredentialsException() {
        super("Invalid email, password, or tenant");
    }
}
