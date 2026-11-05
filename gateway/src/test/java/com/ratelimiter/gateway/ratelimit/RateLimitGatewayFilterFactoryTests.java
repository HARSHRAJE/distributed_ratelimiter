package com.ratelimiter.gateway.ratelimit;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

import com.ratelimiter.gateway.exception.RateLimitExceptionHandler;
import com.ratelimiter.gateway.exception.RateLimitConfigurationException;
import com.ratelimiter.gateway.exception.RedisUnavailableException;
import com.ratelimiter.gateway.policy.PolicyResolver;
import com.ratelimiter.gateway.policy.PolicySnapshot;
import com.ratelimiter.gateway.security.JwtTenantExtractor;
import java.math.BigDecimal;
import java.time.Instant;
import java.util.List;
import io.micrometer.core.instrument.MeterRegistry;
import io.micrometer.core.instrument.simple.SimpleMeterRegistry;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.cloud.gateway.filter.GatewayFilter;
import org.springframework.cloud.gateway.filter.GatewayFilterChain;
import org.springframework.http.HttpStatus;
import org.springframework.mock.http.server.reactive.MockServerHttpRequest;
import org.springframework.mock.web.server.MockServerWebExchange;
import org.springframework.security.oauth2.jwt.Jwt;
import org.springframework.security.oauth2.server.resource.authentication.JwtAuthenticationToken;
import reactor.core.publisher.Mono;
import tools.jackson.databind.json.JsonMapper;

class RateLimitGatewayFilterFactoryTests {

    private static final String TENANT_ID =
        "0795a60c-05af-4ad3-b220-7cc572362aa1";

    private PolicyResolver policyResolver;
    private JwtTenantExtractor tenantExtractor;
    private RateLimitService rateLimitService;
    private RateLimitGatewayFilterFactory factory;
    private RateLimitGatewayFilterFactory.Config config;
    private MeterRegistry meterRegistry;

    @BeforeEach
    void setUp() {
        policyResolver = mock(PolicyResolver.class);
        tenantExtractor = mock(JwtTenantExtractor.class);
        rateLimitService = mock(RateLimitService.class);
        meterRegistry = new SimpleMeterRegistry();
        factory = new RateLimitGatewayFilterFactory(
            policyResolver,
            tenantExtractor,
            rateLimitService,
            new RateLimitExceptionHandler(JsonMapper.builder().build()),
            new RateLimitMetrics(meterRegistry)
        );
        config = new RateLimitGatewayFilterFactory.Config();
        config.setServiceKey("orders-service");
        config.setRouteMappings(List.of(
            "GET|/api/orders|get-orders",
            "POST|/api/orders|create-order"
        ));
    }

    @Test
    void usesMethodAndNormalizedPathToResolvePolicyRoute() {
        PolicySnapshot snapshot = activePolicy();
        when(tenantExtractor.extractTenantId(any()))
            .thenReturn(Mono.just(TENANT_ID));
        when(policyResolver.resolve(
            "orders-service",
            TENANT_ID,
            "get-orders"
        )).thenReturn(Mono.just(snapshot));
        when(rateLimitService.evaluate(snapshot)).thenReturn(Mono.just(
            allowedDecision()
        ));
        MockServerWebExchange exchange = authenticatedExchange(
            "/api//orders/"
        );

        apply(exchange, ignored -> Mono.empty()).block();

        assertThat(exchange.getResponse().getStatusCode()).isNull();
        assertThat(exchange.getResponse().getHeaders()
            .getFirst("X-RateLimit-Remaining-Tenant")).isEqualTo("4");
        assertThat(meterRegistry.get("ratelimit.requests")
            .tag("service", "orders-service")
            .tag("outcome", "allowed")
            .counter()
            .count()).isEqualTo(1);
    }

    @Test
    void rejectsLimitedRequestWithJson429AndRetryAfter() {
        PolicySnapshot snapshot = activePolicy();
        when(tenantExtractor.extractTenantId(any()))
            .thenReturn(Mono.just(TENANT_ID));
        when(policyResolver.resolve(
            "orders-service",
            TENANT_ID,
            "get-orders"
        )).thenReturn(Mono.just(snapshot));
        when(rateLimitService.evaluate(snapshot)).thenReturn(Mono.just(
            new RateLimitDecision(
                RateLimitDecision.Outcome.RATE_LIMITED,
                new TokenBucketResult(
                    false,
                    BigDecimal.ZERO,
                    BigDecimal.ONE,
                    BigDecimal.ONE,
                    1201
                )
            )
        ));
        MockServerWebExchange exchange = authenticatedExchange("/api/orders");

        apply(exchange, ignored -> Mono.error(
            new AssertionError("Limited request must not be forwarded")
        )).block();

        assertThat(exchange.getResponse().getStatusCode())
            .isEqualTo(HttpStatus.TOO_MANY_REQUESTS);
        assertThat(exchange.getResponse().getHeaders().getFirst("Retry-After"))
            .isEqualTo("2");
        String body = exchange.getResponse().getBodyAsString().block();
        assertThat(body).contains("\"error\":\"RATE_LIMIT_EXCEEDED\"");
        assertThat(body).contains("\"retryAfterSeconds\":2");
        assertThat(meterRegistry.get("ratelimit.requests")
            .tag("service", "orders-service")
            .tag("outcome", "rejected")
            .tag("limit_type", "tenant")
            .counter()
            .count()).isEqualTo(1);
    }

    @Test
    void rejectsDisabledPolicy() {
        PolicySnapshot snapshot = new PolicySnapshot(
            "orders-service",
            "policy-id",
            TENANT_ID,
            "get-orders",
            "DISABLED",
            2L,
            1L,
            5,
            BigDecimal.ONE,
            5,
            BigDecimal.ONE,
            BigDecimal.ONE,
            BigDecimal.ONE,
            "MANUAL",
            1L,
            10,
            BigDecimal.ONE,
            BigDecimal.TEN
        );
        when(tenantExtractor.extractTenantId(any()))
            .thenReturn(Mono.just(TENANT_ID));
        when(policyResolver.resolve(
            "orders-service",
            TENANT_ID,
            "get-orders"
        )).thenReturn(Mono.just(snapshot));
        when(rateLimitService.evaluate(snapshot)).thenReturn(Mono.just(
            new RateLimitDecision(
                RateLimitDecision.Outcome.POLICY_DISABLED,
                null
            )
        ));
        MockServerWebExchange exchange = authenticatedExchange("/api/orders");

        apply(exchange, ignored -> Mono.error(
            new AssertionError("Disabled policy must not forward")
        )).block();

        assertThat(exchange.getResponse().getStatusCode())
            .isEqualTo(HttpStatus.FORBIDDEN);
    }

    @Test
    void missingPolicyFailsClosedWithJson503() {
        when(tenantExtractor.extractTenantId(any()))
            .thenReturn(Mono.just(TENANT_ID));
        when(policyResolver.resolve(
            eq("orders-service"),
            eq(TENANT_ID),
            eq("get-orders")
        )).thenReturn(Mono.error(new RateLimitConfigurationException(
            "missing policy"
        )));
        MockServerWebExchange exchange = authenticatedExchange("/api/orders");

        apply(exchange, ignored -> Mono.error(
            new AssertionError("Missing policy must not forward")
        )).block();

        assertThat(exchange.getResponse().getStatusCode())
            .isEqualTo(HttpStatus.SERVICE_UNAVAILABLE);
        assertThat(exchange.getResponse().getBodyAsString().block())
            .contains("\"error\":\"RATE_LIMIT_UNAVAILABLE\"");
    }

    @Test
    void missingTenantClaimReturns401() {
        when(tenantExtractor.extractTenantId(any())).thenReturn(Mono.empty());
        MockServerWebExchange exchange = authenticatedExchange("/api/orders");

        apply(exchange, ignored -> Mono.error(
            new AssertionError("Missing tenant identity must not forward")
        )).block();

        assertThat(exchange.getResponse().getStatusCode())
            .isEqualTo(HttpStatus.UNAUTHORIZED);
    }

    @Test
    void redisFailureDuringBucketCheckReturns503() {
        PolicySnapshot snapshot = activePolicy();
        when(tenantExtractor.extractTenantId(any()))
            .thenReturn(Mono.just(TENANT_ID));
        when(policyResolver.resolve(
            "orders-service",
            TENANT_ID,
            "get-orders"
        )).thenReturn(Mono.just(snapshot));
        when(rateLimitService.evaluate(snapshot)).thenReturn(Mono.error(
            new RedisUnavailableException(
                "redis unavailable",
                new RuntimeException("connection failed")
            )
        ));
        MockServerWebExchange exchange = authenticatedExchange("/api/orders");

        apply(exchange, ignored -> Mono.error(
            new AssertionError("Redis failure must not bypass rate limiting")
        )).block();

        assertThat(exchange.getResponse().getStatusCode())
            .isEqualTo(HttpStatus.SERVICE_UNAVAILABLE);
    }

    @Test
    void methodWithoutConfiguredPolicyFailsClosed() {
        MockServerWebExchange exchange = authenticatedExchange("/api/unmapped");
        GatewayFilter filter = factory.apply(config);

        filter.filter(exchange, ignored -> Mono.empty()).block();

        assertThat(exchange.getResponse().getStatusCode())
            .isEqualTo(HttpStatus.SERVICE_UNAVAILABLE);
    }

    private Mono<Void> apply(
            MockServerWebExchange exchange,
            GatewayFilterChain chain) {
        return factory.apply(config).filter(exchange, chain);
    }

    private MockServerWebExchange authenticatedExchange(String path) {
        Jwt jwt = Jwt.withTokenValue("validated-test-token")
            .header("alg", "RS256")
            .subject("e5f7c071-0106-43d1-bde3-16ae85f62b03")
            .issuedAt(Instant.now())
            .expiresAt(Instant.now().plusSeconds(60))
            .claim("tenant_id", TENANT_ID)
            .build();
        return MockServerWebExchange.builder(
            MockServerHttpRequest.get(path).build()
        ).principal(new JwtAuthenticationToken(jwt)).build();
    }

    private PolicySnapshot activePolicy() {
        return new PolicySnapshot(
            "orders-service",
            "policy-id",
            TENANT_ID,
            "get-orders",
            "ACTIVE",
            1L,
            1L,
            5,
            BigDecimal.TEN,
            5,
            BigDecimal.TEN,
            BigDecimal.ONE,
            BigDecimal.TEN,
            "MANUAL",
            1L,
            10,
            BigDecimal.TEN,
            BigDecimal.valueOf(20)
        );
    }

    private RateLimitDecision allowedDecision() {
        return new RateLimitDecision(
            RateLimitDecision.Outcome.ALLOWED,
            new TokenBucketResult(
                true,
                BigDecimal.valueOf(4),
                BigDecimal.valueOf(3),
                BigDecimal.valueOf(9),
                0
            )
        );
    }
}
