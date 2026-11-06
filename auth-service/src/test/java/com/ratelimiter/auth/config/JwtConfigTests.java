package com.ratelimiter.auth.config;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import com.ratelimiter.auth.config.JwtConfig.JwtKeyPair;
import com.nimbusds.jose.jwk.JWKSet;
import com.nimbusds.jose.jwk.RSAKey;
import com.nimbusds.jose.jwk.source.ImmutableJWKSet;
import com.nimbusds.jose.jwk.source.JWKSource;
import com.nimbusds.jose.proc.SecurityContext;
import java.security.KeyPair;
import java.security.KeyPairGenerator;
import java.security.interfaces.RSAPrivateKey;
import java.security.interfaces.RSAPublicKey;
import java.time.Instant;
import java.util.List;
import java.util.UUID;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.Test;
import org.springframework.security.oauth2.jose.jws.SignatureAlgorithm;
import org.springframework.security.oauth2.jwt.JwtClaimsSet;
import org.springframework.security.oauth2.jwt.JwtDecoder;
import org.springframework.security.oauth2.jwt.JwtEncoder;
import org.springframework.security.oauth2.jwt.JwtEncoderParameters;
import org.springframework.security.oauth2.jwt.JwsHeader;
import org.springframework.security.oauth2.jwt.JwtException;
import org.springframework.security.oauth2.jwt.NimbusJwtEncoder;

class JwtConfigTests {

    private static final String ISSUER = "https://auth.test";
    private static final String AUDIENCE = "rate-limiter-test";
    private static final String SUBJECT =
        "e5f7c071-0106-43d1-bde3-16ae85f62b03";
    private static final String TENANT =
        "0795a60c-05af-4ad3-b220-7cc572362aa1";
    private static KeyPair signingKeys;

    @BeforeAll
    static void generateTestKeys() throws Exception {
        KeyPairGenerator generator = KeyPairGenerator.getInstance("RSA");
        generator.initialize(2048);
        signingKeys = generator.generateKeyPair();
    }

    @Test
    void acceptsValidRs256AccessToken() {
        JwtDecoder decoder = decoder(signingKeys);

        assertThat(decoder.decode(token(
            signingKeys,
            SignatureAlgorithm.RS256,
            ISSUER,
            AUDIENCE,
            TENANT,
            Instant.now().plusSeconds(60)
        )).getClaimAsString("tenant_id")).isEqualTo(TENANT);
    }

    @Test
    void rejectsExpiredToken() {
        assertRejected(token(
            signingKeys,
            SignatureAlgorithm.RS256,
            ISSUER,
            AUDIENCE,
            TENANT,
            Instant.now().minusSeconds(60)
        ));
    }

    @Test
    void rejectsWrongIssuerAndAudience() {
        assertRejected(token(
            signingKeys,
            SignatureAlgorithm.RS256,
            "https://wrong.test",
            AUDIENCE,
            TENANT,
            Instant.now().plusSeconds(60)
        ));
        assertRejected(token(
            signingKeys,
            SignatureAlgorithm.RS256,
            ISSUER,
            "wrong-audience",
            TENANT,
            Instant.now().plusSeconds(60)
        ));
    }

    @Test
    void rejectsTokenWithoutTenantClaim() {
        assertRejected(token(
            signingKeys,
            SignatureAlgorithm.RS256,
            ISSUER,
            AUDIENCE,
            null,
            Instant.now().plusSeconds(60)
        ));
    }

    @Test
    void rejectsUnexpectedSignatureAlgorithmAndSigningKey() throws Exception {
        assertRejected(token(
            signingKeys,
            SignatureAlgorithm.RS512,
            ISSUER,
            AUDIENCE,
            TENANT,
            Instant.now().plusSeconds(60)
        ));
        KeyPairGenerator generator = KeyPairGenerator.getInstance("RSA");
        generator.initialize(2048);
        assertRejected(token(
            generator.generateKeyPair(),
            SignatureAlgorithm.RS256,
            ISSUER,
            AUDIENCE,
            TENANT,
            Instant.now().plusSeconds(60)
        ));
    }

    private static JwtDecoder decoder(KeyPair keyPair) {
        return new JwtConfig().jwtDecoder(new JwtKeyPair(
            (RSAPrivateKey) keyPair.getPrivate(),
            (RSAPublicKey) keyPair.getPublic()
        ), ISSUER, AUDIENCE);
    }

    private static String token(
            KeyPair keyPair,
            SignatureAlgorithm algorithm,
            String issuer,
            String audience,
            String tenantId,
            Instant expiration) {
        RSAKey rsaKey = new RSAKey.Builder(
            (RSAPublicKey) keyPair.getPublic()
        ).privateKey(
            (RSAPrivateKey) keyPair.getPrivate()
        ).algorithm(
            com.nimbusds.jose.JWSAlgorithm.parse(algorithm.getName())
        ).build();
        JWKSource<SecurityContext> jwkSource =
            new ImmutableJWKSet<>(new JWKSet(rsaKey));
        JwtEncoder encoder = new NimbusJwtEncoder(jwkSource);
        Instant now = Instant.now();
        Instant issuedAt = expiration.isBefore(now)
            ? expiration.minusSeconds(60)
            : now.minusSeconds(1);
        JwtClaimsSet.Builder claims = JwtClaimsSet.builder()
            .issuer(issuer)
            .subject(SUBJECT)
            .audience(List.of(audience))
            .issuedAt(issuedAt)
            .expiresAt(expiration)
            .claim("roles", List.of("TENANT_ADMIN"))
            .claim("token_type", "access");
        if (tenantId != null) {
            claims.claim("tenant_id", tenantId);
        }
        return encoder.encode(JwtEncoderParameters.from(
            JwsHeader.with(algorithm).build(),
            claims.build()
        )).getTokenValue();
    }

    private static void assertRejected(String token) {
        assertThatThrownBy(() -> decoder(signingKeys).decode(token))
            .isInstanceOf(JwtException.class);
    }
}
