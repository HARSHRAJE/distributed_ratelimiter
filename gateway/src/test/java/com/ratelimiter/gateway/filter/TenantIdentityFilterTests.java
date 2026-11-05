package com.ratelimiter.gateway.filter;

import static org.assertj.core.api.Assertions.assertThat;

import java.time.Instant;
import org.junit.jupiter.api.Test;
import org.springframework.mock.http.server.reactive.MockServerHttpRequest;
import org.springframework.mock.web.server.MockServerWebExchange;
import org.springframework.security.oauth2.jwt.Jwt;
import org.springframework.security.oauth2.server.resource.authentication.JwtAuthenticationToken;
import reactor.core.publisher.Mono;

class TenantIdentityFilterTests {

    private static final String USER_ID =
        "e5f7c071-0106-43d1-bde3-16ae85f62b03";
    private static final String TENANT_ID =
        "0795a60c-05af-4ad3-b220-7cc572362aa1";

    private final TenantIdentityFilter filter = new TenantIdentityFilter();

    @Test
    void replacesClientIdentityHeadersWithValidatedClaims() {
        JwtAuthenticationToken authentication = authentication();
        MockServerWebExchange exchange = MockServerWebExchange
            .builder(MockServerHttpRequest.get("/api/orders")
                .header("X-Tenant-Id", "client-tenant")
                .header("X-User-Id", "client-user")
                .build())
            .principal(authentication)
            .build();

        filter.filter(exchange, forwarded -> {
            assertThat(forwarded.getRequest().getHeaders().getFirst("X-Tenant-Id"))
                .isEqualTo(TENANT_ID);
            assertThat(forwarded.getRequest().getHeaders().getFirst("X-User-Id"))
                .isEqualTo(USER_ID);
            return Mono.empty();
        }).block();
    }

    @Test
    void removesClientIdentityHeadersWhenRequestIsUnauthenticated() {
        MockServerWebExchange exchange = MockServerWebExchange
            .from(MockServerHttpRequest.get("/api/orders")
                .header("X-Tenant-Id", "client-tenant")
                .header("X-User-Id", "client-user")
                .build());

        filter.filter(exchange, forwarded -> {
            assertThat(forwarded.getRequest().getHeaders().getFirst("X-Tenant-Id"))
                .isNull();
            assertThat(forwarded.getRequest().getHeaders().getFirst("X-User-Id"))
                .isNull();
            return Mono.empty();
        }).block();
    }

    private JwtAuthenticationToken authentication() {
        Instant now = Instant.now();
        Jwt jwt = Jwt.withTokenValue("validated-test-token")
            .header("alg", "RS256")
            .subject(USER_ID)
            .issuedAt(now)
            .expiresAt(now.plusSeconds(60))
            .claim("tenant_id", TENANT_ID)
            .claim("roles", java.util.List.of("TENANT_ADMIN"))
            .build();
        return new JwtAuthenticationToken(jwt);
    }
}
