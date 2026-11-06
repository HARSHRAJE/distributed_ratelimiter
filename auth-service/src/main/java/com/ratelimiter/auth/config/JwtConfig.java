package com.ratelimiter.auth.config;

import java.io.IOException;
import java.security.interfaces.RSAPrivateKey;
import java.security.interfaces.RSAPublicKey;
import java.util.UUID;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.core.io.Resource;
import org.springframework.security.oauth2.jose.jws.SignatureAlgorithm;
import org.springframework.security.oauth2.jwt.JwtDecoder;
import org.springframework.security.oauth2.jwt.JwtEncoder;
import org.springframework.security.oauth2.jwt.JwtValidators;
import org.springframework.security.oauth2.jwt.NimbusJwtDecoder;
import org.springframework.security.oauth2.jwt.NimbusJwtEncoder;
import org.springframework.security.converter.RsaKeyConverters;
import org.springframework.security.oauth2.core.OAuth2Error;
import org.springframework.security.oauth2.core.OAuth2TokenValidatorResult;
import org.springframework.security.oauth2.jwt.Jwt;
import com.nimbusds.jose.jwk.JWKSet;
import com.nimbusds.jose.jwk.RSAKey;
import com.nimbusds.jose.jwk.source.ImmutableJWKSet;
import com.nimbusds.jose.jwk.source.JWKSource;
import com.nimbusds.jose.proc.SecurityContext;

@Configuration
public class JwtConfig {

    @Bean
    public JwtKeyPair jwtKeyPair(
            @Value("${auth.jwt.private-key-location}") Resource privateKeyResource,
            @Value("${auth.jwt.public-key-location}") Resource publicKeyResource)
            throws IOException {

        RSAPrivateKey privateKey;
        try (var inputStream = privateKeyResource.getInputStream()) {
            privateKey = RsaKeyConverters.pkcs8().convert(inputStream);
        }

        RSAPublicKey publicKey;
        try (var inputStream = publicKeyResource.getInputStream()) {
            publicKey = RsaKeyConverters.x509().convert(inputStream);
        }

        if (!privateKey.getModulus().equals(publicKey.getModulus())) {
            throw new IllegalStateException(
                "Configured JWT public and private keys do not match"
            );
        }

        return new JwtKeyPair(privateKey, publicKey);
    }

    @Bean
    public JwtEncoder jwtEncoder(JwtKeyPair keyPair) {
        RSAKey rsaKey = new RSAKey.Builder(keyPair.publicKey())
            .privateKey(keyPair.privateKey())
            .algorithm(com.nimbusds.jose.JWSAlgorithm.RS256)
            .build();
        JWKSource<SecurityContext> jwkSource =
            new ImmutableJWKSet<>(new JWKSet(rsaKey));
        return new NimbusJwtEncoder(jwkSource);
    }

    @Bean
    public JwtDecoder jwtDecoder(
            JwtKeyPair keyPair,
            @Value("${auth.jwt.issuer}") String issuer,
            @Value("${auth.jwt.audience}") String audience) {
        NimbusJwtDecoder decoder = NimbusJwtDecoder
            .withPublicKey(keyPair.publicKey())
            .signatureAlgorithm(SignatureAlgorithm.RS256)
            .build();
        var issuerValidator = JwtValidators.createDefaultWithIssuer(issuer);
        decoder.setJwtValidator(jwt -> {
            var issuerResult = issuerValidator.validate(jwt);
            if (issuerResult.hasErrors()) {
                return issuerResult;
            }
            if (!jwt.getAudience().contains(audience)) {
                return OAuth2TokenValidatorResult.failure(
                    new OAuth2Error(
                        "invalid_token",
                        "Invalid token audience",
                        null
                    )
                );
            }
            if (!"access".equals(jwt.getClaimAsString("token_type"))) {
                return OAuth2TokenValidatorResult.failure(
                    new OAuth2Error(
                        "invalid_token",
                        "Invalid token type",
                        null
                    )
                );
            }
            if (!isUuid(jwt.getSubject())
                    || !isUuid(jwt.getClaimAsString("tenant_id"))
                    || jwt.getClaimAsStringList("roles") == null
                    || jwt.getClaimAsStringList("roles").isEmpty()) {
                return OAuth2TokenValidatorResult.failure(
                    new OAuth2Error(
                        "invalid_token",
                        "A valid user, tenant, and role claim is required",
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

    public record JwtKeyPair(
        RSAPrivateKey privateKey,
        RSAPublicKey publicKey
    ) {}
}
