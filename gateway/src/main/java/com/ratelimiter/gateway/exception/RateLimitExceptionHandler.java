package com.ratelimiter.gateway.exception;

import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.stereotype.Component;
import org.springframework.web.server.ServerWebExchange;
import reactor.core.publisher.Mono;
import tools.jackson.core.JacksonException;
import tools.jackson.databind.ObjectMapper;

@Component
public class RateLimitExceptionHandler {

    private final ObjectMapper objectMapper;

    public RateLimitExceptionHandler(ObjectMapper objectMapper) {
        this.objectMapper = objectMapper;
    }

    public Mono<Void> handle(
            ServerWebExchange exchange,
            Throwable exception) {
        if (exception instanceof RedisUnavailableException
                || exception instanceof RateLimitConfigurationException) {
            return write(
                exchange,
                HttpStatus.SERVICE_UNAVAILABLE,
                "RATE_LIMIT_UNAVAILABLE",
                "Rate-limit service is temporarily unavailable.",
                null
            );
        }
        return Mono.error(exception);
    }

    public Mono<Void> write(
            ServerWebExchange exchange,
            HttpStatus status,
            String error,
            String message,
            Long retryAfterSeconds) {
        if (exchange.getResponse().isCommitted()) {
            return Mono.error(new IllegalStateException(
                "Cannot write a rate-limit error after the response is committed"
            ));
        }
        exchange.getResponse().setStatusCode(status);
        exchange.getResponse().getHeaders().setContentType(
            MediaType.APPLICATION_JSON
        );
        if (retryAfterSeconds != null) {
            exchange.getResponse().getHeaders().set(
                "Retry-After",
                Long.toString(retryAfterSeconds)
            );
        }
        byte[] body;
        try {
            body = objectMapper.writeValueAsBytes(
                new RateLimitError(
                    status.value(),
                    error,
                    message,
                    retryAfterSeconds
                )
            );
        } catch (JacksonException exception) {
            return Mono.error(new IllegalStateException(
                "Could not serialize rate-limit error response",
                exception
            ));
        }
        return exchange.getResponse().writeWith(Mono.just(
            exchange.getResponse().bufferFactory().wrap(body)
        ));
    }

    public record RateLimitError(
        int status,
        String error,
        String message,
        Long retryAfterSeconds
    ) {}
}
