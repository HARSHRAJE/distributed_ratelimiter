package com.ratelimiter.policy.config;

import java.io.IOException;
import java.security.interfaces.RSAPublicKey;
import java.time.Duration;
import java.util.List;
import java.util.UUID;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.core.io.Resource;
import org.springframework.http.HttpMethod;
import org.springframework.security.config.annotation.method.configuration.EnableMethodSecurity;
import org.springframework.security.config.annotation.web.builders.HttpSecurity;
import org.springframework.security.config.http.SessionCreationPolicy;
import org.springframework.security.core.GrantedAuthority;
import org.springframework.security.core.authority.SimpleGrantedAuthority;
import org.springframework.security.converter.RsaKeyConverters;
import org.springframework.security.oauth2.core.OAuth2Error;
import org.springframework.security.oauth2.core.OAuth2TokenValidator;
import org.springframework.security.oauth2.core.OAuth2TokenValidatorResult;
import org.springframework.security.oauth2.jose.jws.SignatureAlgorithm;
import org.springframework.security.oauth2.jwt.Jwt;
import org.springframework.security.oauth2.jwt.JwtDecoder;
import org.springframework.security.oauth2.jwt.JwtIssuerValidator;
import org.springframework.security.oauth2.jwt.JwtTimestampValidator;
import org.springframework.security.oauth2.jwt.NimbusJwtDecoder;
import org.springframework.security.oauth2.server.resource.authentication.JwtAuthenticationConverter;
import org.springframework.security.web.SecurityFilterChain;

@Configuration
@EnableMethodSecurity
public class PolicySecurityConfig {

    @Bean
    public SecurityFilterChain policySecurityFilterChain(
            HttpSecurity http,
            JwtDecoder policyJwtDecoder) throws Exception {
        JwtAuthenticationConverter converter =
            new JwtAuthenticationConverter();
        converter.setJwtGrantedAuthoritiesConverter(jwt -> {
            List<String> roles = jwt.getClaimAsStringList("roles");
            if (roles == null) {
                return List.of();
            }
            return roles.stream()
                .<GrantedAuthority>map(role ->
                    new SimpleGrantedAuthority("ROLE_" + role))
                .toList();
        });

        return http
            .csrf(csrf -> csrf.disable())
            .sessionManagement(session -> session
                .sessionCreationPolicy(SessionCreationPolicy.STATELESS)
            )
            .authorizeHttpRequests(authorize -> authorize
                .requestMatchers(
                    "/actuator/health",
                    "/actuator/prometheus"
                ).permitAll()
                .requestMatchers(
                    HttpMethod.PUT,
                    "/api/v1/services/*/adaptive-configuration",
                    "/api/v1/services/*/adaptive-rollback",
                    "/api/v1/services/by-key/*/adaptive-control",
                    "/api/v1/services/execution-control"
                ).permitAll()
                .requestMatchers(
                    HttpMethod.GET,
                    "/api/v1/services/*/configuration/executions/*",
                    "/api/v1/services/*/configuration/rollbacks/*",
                    "/api/v1/services/by-key/*/effective-configuration"
                ).permitAll()
                .anyRequest().authenticated()
            )
            .oauth2ResourceServer(resourceServer -> resourceServer
                .jwt(jwt -> jwt
                    .decoder(policyJwtDecoder)
                    .jwtAuthenticationConverter(converter)
                )
            )
            .build();
    }

    @Bean
    public JwtDecoder policyJwtDecoder(
            @Value("${security.jwt.public-key-location}") Resource keyResource,
            @Value("${security.jwt.issuer}") String issuer,
            @Value("${security.jwt.audience}") String audience)
            throws IOException {
        RSAPublicKey publicKey;
        try (var inputStream = keyResource.getInputStream()) {
            publicKey = RsaKeyConverters.x509().convert(inputStream);
        }

        NimbusJwtDecoder decoder = NimbusJwtDecoder
            .withPublicKey(publicKey)
            .signatureAlgorithm(SignatureAlgorithm.RS256)
            .build();
        OAuth2TokenValidator<Jwt> timestamp =
            new JwtTimestampValidator(Duration.ZERO);
        OAuth2TokenValidator<Jwt> issuerValidator =
            new JwtIssuerValidator(issuer);
        decoder.setJwtValidator(jwt -> {
            OAuth2TokenValidatorResult timeResult =
                timestamp.validate(jwt);
            if (timeResult.hasErrors()) {
                return timeResult;
            }
            OAuth2TokenValidatorResult issuerResult =
                issuerValidator.validate(jwt);
            if (issuerResult.hasErrors()) {
                return issuerResult;
            }
            if (!jwt.getAudience().contains(audience)
                    || !"access".equals(
                        jwt.getClaimAsString("token_type"))
                    || jwt.getClaimAsStringList("roles") == null
                    || jwt.getClaimAsStringList("roles").isEmpty()
                    || !isUuid(jwt.getSubject())
                    || !isUuid(jwt.getClaimAsString("tenant_id"))) {
                return OAuth2TokenValidatorResult.failure(
                    new OAuth2Error(
                        "invalid_token",
                        "Required access-token claims are missing",
                        null
                    )
                );
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
