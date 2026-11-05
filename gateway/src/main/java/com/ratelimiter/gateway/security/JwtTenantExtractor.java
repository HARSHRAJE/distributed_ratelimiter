package com.ratelimiter.gateway.security;

import org.springframework.security.oauth2.server.resource.authentication.JwtAuthenticationToken;
import org.springframework.stereotype.Component;
import reactor.core.publisher.Mono;
import org.springframework.web.server.ServerWebExchange;

@Component
public class JwtTenantExtractor {

    public Mono<String> extractTenantId(ServerWebExchange exchange) {
        return exchange.getPrincipal()
            .ofType(JwtAuthenticationToken.class)
            .map(authentication ->
                authentication.getToken().getClaimAsString("tenant_id")
            )
            .filter(tenantId -> tenantId != null && !tenantId.isBlank());
    }
}
