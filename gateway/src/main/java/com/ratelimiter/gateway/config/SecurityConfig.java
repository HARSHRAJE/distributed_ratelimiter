package com.ratelimiter.gateway.config;

import java.io.IOException;
import java.security.interfaces.RSAPublicKey;
import java.util.ArrayList;
import java.util.List;
import java.util.UUID;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.core.convert.converter.Converter;
import org.springframework.core.io.Resource;
import org.springframework.security.authentication.AbstractAuthenticationToken;
import org.springframework.security.config.web.server.ServerHttpSecurity;
import org.springframework.security.core.authority.SimpleGrantedAuthority;
import org.springframework.security.core.GrantedAuthority;
import org.springframework.security.oauth2.core.OAuth2Error;
import org.springframework.security.oauth2.core.OAuth2TokenValidator;
import org.springframework.security.oauth2.core.OAuth2TokenValidatorResult;
import org.springframework.security.oauth2.jwt.Jwt;
import org.springframework.security.oauth2.jwt.JwtIssuerValidator;
import org.springframework.security.oauth2.jwt.JwtTimestampValidator;
import org.springframework.security.oauth2.jwt.NimbusReactiveJwtDecoder;
import org.springframework.security.oauth2.jwt.ReactiveJwtDecoder;
import org.springframework.security.oauth2.jose.jws.SignatureAlgorithm;
import org.springframework.security.converter.RsaKeyConverters;
import java.time.Duration;
import org.springframework.security.oauth2.server.resource.authentication.JwtAuthenticationConverter;
import org.springframework.security.oauth2.server.resource.authentication.ReactiveJwtAuthenticationConverterAdapter;
import org.springframework.security.web.server.SecurityWebFilterChain;
import reactor.core.publisher.Mono;

@Configuration
public class SecurityConfig {

    @Bean
    public SecurityWebFilterChain securityWebFilterChain(
            ServerHttpSecurity http) {

        JwtAuthenticationConverter authoritiesConverter =
            new JwtAuthenticationConverter();
        authoritiesConverter.setJwtGrantedAuthoritiesConverter(jwt -> {
            List<String> roles = jwt.getClaimAsStringList("roles");
            if (roles == null) {
                return List.of();
            }
            return roles.stream()
                .<GrantedAuthority>map(role ->
                    new SimpleGrantedAuthority("ROLE_" + role))
                .toList();
        });

        Converter<Jwt, Mono<AbstractAuthenticationToken>> reactiveConverter =
            new ReactiveJwtAuthenticationConverterAdapter(authoritiesConverter);

        return http
            .csrf(ServerHttpSecurity.CsrfSpec::disable)
            .authorizeExchange(exchanges -> exchanges
                .pathMatchers(
                    "/actuator/health",
                    "/actuator/prometheus",
                    "/api/v1/auth/register",
                    "/api/v1/auth/login",
                    "/api/v1/auth/refresh",
                    "/api/v1/auth/logout",
                    "/api/v1/auth/admin/bootstrap"
                ).permitAll()
                .pathMatchers("/api/orders", "/api/orders/**")
                    .hasAnyRole("TENANT_ADMIN", "TENANT_MEMBER")
                .anyExchange().authenticated()
            )
            .oauth2ResourceServer(resourceServer ->
                resourceServer.jwt(jwt ->
                    jwt.jwtAuthenticationConverter(reactiveConverter)
                )
            )
            .build();
    }

    @Bean
    public ReactiveJwtDecoder jwtDecoder(
            @Value("${security.jwt.public-key-location}") Resource publicKeyResource,
            @Value("${security.jwt.issuer}") String issuer,
            @Value("${security.jwt.audience}") String audience)
            throws IOException {

        RSAPublicKey publicKey;
        try (var inputStream = publicKeyResource.getInputStream()) {
            publicKey = RsaKeyConverters.x509().convert(inputStream);
        }

        NimbusReactiveJwtDecoder decoder =
            NimbusReactiveJwtDecoder.withPublicKey(publicKey)
                .signatureAlgorithm(SignatureAlgorithm.RS256)
                .build();

        List<OAuth2TokenValidator<Jwt>> validators = new ArrayList<>();
        validators.add(new JwtTimestampValidator(Duration.ZERO));
        validators.add(new JwtIssuerValidator(issuer));
        validators.add(jwt -> jwt.getAudience().contains(audience)
            ? OAuth2TokenValidatorResult.success()
            : OAuth2TokenValidatorResult.failure(
                new OAuth2Error("invalid_token", "Invalid token audience", null)
            ));
        validators.add(jwt -> "access".equals(jwt.getClaimAsString("token_type"))
            ? OAuth2TokenValidatorResult.success()
            : OAuth2TokenValidatorResult.failure(
                new OAuth2Error("invalid_token", "Invalid token type", null)
            ));
        validators.add(jwt -> {
            String subject = jwt.getSubject();
            String tenantId = jwt.getClaimAsString("tenant_id");
            List<String> roles = jwt.getClaimAsStringList("roles");
            return isUuid(subject)
                    && isUuid(tenantId)
                    && roles != null
                    && !roles.isEmpty()
                    && roles.stream().allMatch(role ->
                        role != null && !role.isBlank())
                ? OAuth2TokenValidatorResult.success()
                : OAuth2TokenValidatorResult.failure(
                    new OAuth2Error(
                        "invalid_token",
                        "A valid user, tenant, and role claim is required",
                        null
                    )
                );
        });

        decoder.setJwtValidator(jwt -> {
            for (OAuth2TokenValidator<Jwt> validator : validators) {
                OAuth2TokenValidatorResult result = validator.validate(jwt);
                if (result.hasErrors()) {
                    return result;
                }
            }
            return OAuth2TokenValidatorResult.success();
        });
        return decoder;
    }

    private static boolean isUuid(String value) {
        if (value == null || value.isBlank()) {
            return false;
        }
        try {
            UUID.fromString(value);
            return true;
        } catch (IllegalArgumentException exception) {
            return false;
        }
    }
}
