package com.ratelimiter.gateway.filter;

import org.springframework.cloud.gateway.filter.GatewayFilterChain;
import org.springframework.cloud.gateway.filter.GlobalFilter;
import org.springframework.core.Ordered;
import org.springframework.security.oauth2.server.resource.authentication.JwtAuthenticationToken;
import org.springframework.stereotype.Component;
import org.springframework.web.server.ServerWebExchange;
import reactor.core.publisher.Mono;

@Component
public class TenantIdentityFilter implements GlobalFilter, Ordered {

    @Override
    public int getOrder() {
        return Ordered.LOWEST_PRECEDENCE;
    }

    @Override
    public Mono<Void> filter(
            ServerWebExchange exchange,
            GatewayFilterChain chain) {

        return exchange.getPrincipal()
            .ofType(JwtAuthenticationToken.class)
            .map(authentication -> {
                var jwt = authentication.getToken();
                return new TrustedIdentity(
                    jwt.getSubject(),
                    jwt.getClaimAsString("tenant_id")
                );
            })
            .map(identity -> exchangeWithTrustedIdentity(exchange, identity))
            .defaultIfEmpty(exchangeWithTrustedIdentity(exchange, null))
            .flatMap(chain::filter);
    }

    private ServerWebExchange exchangeWithTrustedIdentity(
            ServerWebExchange exchange,
            TrustedIdentity identity) {

        return exchange.mutate()
            .request(request -> request.headers(headers -> {
                headers.remove("X-Tenant-Id");
                headers.remove("X-User-Id");
                if (identity != null) {
                    headers.set("X-Tenant-Id", identity.tenantId());
                    headers.set("X-User-Id", identity.userId());
                }
            }))
            .build();
    }

    private record TrustedIdentity(String userId, String tenantId) {}
}