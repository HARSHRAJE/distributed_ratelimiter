package com.ratelimiter.gateway.ratelimit;

import com.ratelimiter.gateway.exception.RateLimitExceptionHandler;
import com.ratelimiter.gateway.policy.PolicyResolver;
import com.ratelimiter.gateway.policy.PolicySnapshot;
import com.ratelimiter.gateway.security.JwtTenantExtractor;
import java.math.BigDecimal;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.List;
import org.springframework.cloud.gateway.filter.GatewayFilter;
import org.springframework.cloud.gateway.filter.GatewayFilterChain;
import org.springframework.cloud.gateway.filter.factory.AbstractGatewayFilterFactory;
import org.springframework.http.HttpStatus;
import org.springframework.http.server.PathContainer;
import org.springframework.stereotype.Component;
import org.springframework.web.server.ServerWebExchange;
import org.springframework.web.util.pattern.PathPattern;
import org.springframework.web.util.pattern.PathPatternParser;
import reactor.core.publisher.Mono;

@Component
public class RateLimitGatewayFilterFactory
        extends AbstractGatewayFilterFactory<
            RateLimitGatewayFilterFactory.Config> {

    private final PolicyResolver policyResolver;
    private final JwtTenantExtractor tenantExtractor;
    private final RateLimitService rateLimitService;
    private final RateLimitExceptionHandler exceptionHandler;
    private final RateLimitMetrics rateLimitMetrics;

    public RateLimitGatewayFilterFactory(
            PolicyResolver policyResolver,
            JwtTenantExtractor tenantExtractor,
            RateLimitService rateLimitService,
            RateLimitExceptionHandler exceptionHandler,
            RateLimitMetrics rateLimitMetrics) {
        super(Config.class);
        this.policyResolver = policyResolver;
        this.tenantExtractor = tenantExtractor;
        this.rateLimitService = rateLimitService;
        this.exceptionHandler = exceptionHandler;
        this.rateLimitMetrics = rateLimitMetrics;
    }

    @Override
    public List<String> shortcutFieldOrder() {
        return List.of("serviceKey", "routeMappings");
    }

    @Override
    public GatewayFilter apply(Config config) {
        if (config.routeMappings == null || config.routeMappings.isEmpty()) {
            throw new IllegalArgumentException(
                "Rate-limit route mappings must be configured"
            );
        }

        List<RouteMapping> mappings = compileMappings(config.routeMappings);
        return (exchange, chain) -> {
            RouteMapping mapping = findMapping(
                exchange,
                mappings
            );
            if (mapping == null) {
                return exceptionHandler.write(
                    exchange,
                    HttpStatus.SERVICE_UNAVAILABLE,
                    "RATE_LIMIT_UNAVAILABLE",
                    "Rate-limit policy is not configured for this route.",
                    null
                );
            }

            String serviceKey = config.serviceKey;
            if (serviceKey == null || serviceKey.isBlank()) {
                var route = exchange.getAttribute(
                    org.springframework.cloud.gateway.support.ServerWebExchangeUtils.GATEWAY_ROUTE_ATTR
                );
                if (route instanceof org.springframework.cloud.gateway.route.Route gatewayRoute) {
                    serviceKey = gatewayRoute.getId();
                }
            }
            if (serviceKey == null || serviceKey.isBlank()) {
                return exceptionHandler.write(
                    exchange,
                    HttpStatus.SERVICE_UNAVAILABLE,
                    "RATE_LIMIT_UNAVAILABLE",
                    "Rate-limit service is not configured for this route.",
                    null
                );
            }

            String selectedServiceKey = serviceKey;
            return tenantExtractor.extractTenantId(exchange)
                .switchIfEmpty(Mono.error(
                    new MissingTenantIdentityException()
                ))
                .flatMap(tenantId -> policyResolver.resolve(
                        selectedServiceKey,
                        tenantId,
                        mapping.routeId()
                    )
                    .flatMap(snapshot ->
                        rateLimitService.evaluate(snapshot)
                    )
                    .flatMap(decision -> applyDecision(
                        exchange,
                        chain,
                        decision,
                        selectedServiceKey
                    ))
                )
                .onErrorResume(
                    MissingTenantIdentityException.class,
                    exception -> exceptionHandler.write(
                        exchange,
                        HttpStatus.UNAUTHORIZED,
                        "UNAUTHENTICATED",
                        "A validated tenant identity is required.",
                        null
                    )
                )
                .onErrorResume(
                    exception -> exceptionHandler.handle(exchange, exception)
                );
        };
    }

    private Mono<Void> applyDecision(
            ServerWebExchange exchange,
            GatewayFilterChain chain,
            RateLimitDecision decision,
            String serviceKey) {
        if (decision.outcome() == RateLimitDecision.Outcome.POLICY_DISABLED) {
            rateLimitMetrics.recordRejected(serviceKey, "policy");
            return exceptionHandler.write(
                exchange,
                HttpStatus.FORBIDDEN,
                "POLICY_DISABLED",
                "Rate-limit policy is disabled.",
                null
            );
        }
        if (decision.outcome() == RateLimitDecision.Outcome.RATE_LIMITED) {
            rateLimitMetrics.recordRejected(
                serviceKey,
                limitingBucket(decision.bucketResult())
            );
            long retryAfterSeconds = Math.max(
                1,
                (decision.bucketResult().retryAfterMillis() + 999) / 1000
            );
            return exceptionHandler.write(
                exchange,
                HttpStatus.TOO_MANY_REQUESTS,
                "RATE_LIMIT_EXCEEDED",
                "Rate limit exceeded",
                retryAfterSeconds
            );
        }

        rateLimitMetrics.recordAllowed(serviceKey);
        setQuotaHeaders(exchange, decision.bucketResult());
        return chain.filter(exchange);
    }

    private static String limitingBucket(TokenBucketResult result) {
        if (result.tenantRemaining().compareTo(BigDecimal.ONE) < 0) {
            return "tenant";
        }
        if (result.routeRemaining().compareTo(BigDecimal.ONE) < 0) {
            return "route";
        }
        return "service";
    }

    private static void setQuotaHeaders(
            ServerWebExchange exchange,
            TokenBucketResult result) {
        exchange.getResponse().getHeaders().set(
            "X-RateLimit-Remaining-Tenant",
            result.tenantRemaining().stripTrailingZeros().toPlainString()
        );
        exchange.getResponse().getHeaders().set(
            "X-RateLimit-Remaining-Route",
            result.routeRemaining().stripTrailingZeros().toPlainString()
        );
        exchange.getResponse().getHeaders().set(
            "X-RateLimit-Remaining-Service",
            result.globalRemaining().stripTrailingZeros().toPlainString()
        );
    }

    private static List<RouteMapping> compileMappings(
            List<String> routeMappings) {
        PathPatternParser parser = new PathPatternParser();
        List<RouteMapping> mappings = new ArrayList<>();
        routeMappings.forEach(entry -> {
            String[] parts = entry.split("\\|", -1);
            if (parts.length != 3 || parts[0].isBlank()
                    || parts[1].isBlank() || parts[2].isBlank()) {
                throw new IllegalArgumentException(
                    "Route mapping must be METHOD|/path-pattern|route-id: "
                        + entry
                );
            }
            String method = parts[0]
                .toUpperCase(java.util.Locale.ROOT);
            String pathPattern = normalizePath(parts[1]);
            mappings.add(new RouteMapping(
                method,
                parser.parse(pathPattern),
                pathPattern,
                parts[2]
            ));
        });
        mappings.sort(Comparator.comparingInt(
            (RouteMapping mapping) -> mapping.patternText().length()
        ).reversed());
        return List.copyOf(mappings);
    }

    private static RouteMapping findMapping(
            ServerWebExchange exchange,
            List<RouteMapping> mappings) {
        String method = exchange.getRequest().getMethod().name();
        String path = normalizePath(
            exchange.getRequest().getURI().getPath()
        );
        PathContainer pathContainer = PathContainer.parsePath(path);
        return mappings.stream()
            .filter(mapping -> mapping.method().equals(method))
            .filter(mapping -> mapping.pattern().matches(pathContainer))
            .findFirst()
            .orElse(null);
    }

    private static String normalizePath(String path) {
        String normalized = path.replaceAll("/{2,}", "/");
        if (normalized.length() > 1 && normalized.endsWith("/")) {
            return normalized.substring(0, normalized.length() - 1);
        }
        return normalized;
    }

    public static class Config {

        private String serviceKey;
        private List<String> routeMappings;

        public String getServiceKey() {
            return serviceKey;
        }

        public void setServiceKey(String serviceKey) {
            this.serviceKey = serviceKey;
        }

        public List<String> getRouteMappings() {
            return routeMappings;
        }

        public void setRouteMappings(List<String> routeMappings) {
            this.routeMappings = routeMappings;
        }
    }

    private record RouteMapping(
        String method,
        PathPattern pattern,
        String patternText,
        String routeId
    ) {}

    private static final class MissingTenantIdentityException
            extends RuntimeException {}
}
