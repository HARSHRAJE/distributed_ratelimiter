package com.ratelimiter.gateway.config;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import com.nimbusds.jose.jwk.JWKSet;
import com.nimbusds.jose.jwk.RSAKey;
import com.nimbusds.jose.jwk.source.ImmutableJWKSet;
import com.nimbusds.jose.jwk.source.JWKSource;
import com.nimbusds.jose.proc.SecurityContext;
import java.nio.file.Files;
import java.nio.file.Path;
import java.security.KeyPair;
import java.security.KeyPairGenerator;
import java.time.Instant;
import java.util.List;
import java.util.UUID;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import org.springframework.core.io.FileSystemResource;
import org.springframework.security.oauth2.jose.jws.SignatureAlgorithm;
import org.springframework.security.oauth2.jwt.JwtClaimsSet;
import org.springframework.security.oauth2.jwt.JwtEncoder;
import org.springframework.security.oauth2.jwt.JwtEncoderParameters;
import org.springframework.security.oauth2.jwt.JwsHeader;
import org.springframework.security.oauth2.jwt.JwtException;
import org.springframework.security.oauth2.jwt.NimbusJwtEncoder;
import org.springframework.security.oauth2.jwt.ReactiveJwtDecoder;

class JwtDecoderTests {

    private static final String ISSUER = "https://auth.example.test";
    private static final String AUDIENCE = "rate-limiter-api";
    private static final UUID SUBJECT =
        UUID.fromString("e5f7c071-0106-43d1-bde3-16ae85f62b03");
    private static final UUID TENANT =
        UUID.fromString("0795a60c-05af-4ad3-b220-7cc572362aa1");

    @TempDir
    Path temporaryDirectory;

    private JwtEncoder encoder;
    private ReactiveJwtDecoder decoder;

    @BeforeEach
    void setUp() throws Exception {
        KeyPairGenerator generator = KeyPairGenerator.getInstance("RSA");
        generator.initialize(2048);
        KeyPair keyPair = generator.generateKeyPair();

        Files.write(
            temporaryDirectory.resolve("public.pem"),
            pem("PUBLIC KEY", keyPair.getPublic().getEncoded())
        );

        RSAKey rsaKey = new RSAKey.Builder(
                (java.security.interfaces.RSAPublicKey) keyPair.getPublic()
            )
            .privateKey(
                (java.security.interfaces.RSAPrivateKey) keyPair.getPrivate()
            )
            .algorithm(com.nimbusds.jose.JWSAlgorithm.RS256)
            .build();
        JWKSource<SecurityContext> jwkSource =
            new ImmutableJWKSet<>(new JWKSet(rsaKey));
        encoder = new NimbusJwtEncoder(jwkSource);
        decoder = new SecurityConfig().jwtDecoder(
            new FileSystemResource(
                temporaryDirectory.resolve("public.pem").toFile()
            ),
            ISSUER,
            AUDIENCE
        );
    }

    @Test
    void acceptsValidRs256AccessToken() {
        assertThat(decoder.decode(token(ISSUER, AUDIENCE, Instant.now().plusSeconds(60)))
            .block()
            .getSubject()).isEqualTo(SUBJECT.toString());
    }

    @Test
    void rejectsModifiedSignature() {
        String token = token(ISSUER, AUDIENCE, Instant.now().plusSeconds(60));
        int signatureStart = token.lastIndexOf('.') + 1;
        char replacement = token.charAt(signatureStart) == 'a' ? 'b' : 'a';
        String tampered = token.substring(0, signatureStart)
            + replacement
            + token.substring(signatureStart + 1);

        assertThatThrownBy(() -> decoder.decode(tampered).block())
            .isInstanceOf(JwtException.class);
    }

    @Test
    void rejectsExpiredToken() {
        assertRejected(token(
            ISSUER,
            AUDIENCE,
            Instant.now().minusSeconds(1)
        ));
    }

    @Test
    void rejectsIncorrectIssuer() {
        assertRejected(token(
            "https://other.example.test",
            AUDIENCE,
            Instant.now().plusSeconds(60)
        ));
    }

    @Test
    void rejectsIncorrectAudience() {
        assertRejected(token(
            ISSUER,
            "another-api",
            Instant.now().plusSeconds(60)
        ));
    }

    @Test
    void rejectsMissingOrInvalidSubjectAndTenantClaims() {
        assertRejected(token(
            ISSUER,
            AUDIENCE,
            Instant.now().plusSeconds(60),
            "not-a-uuid",
            TENANT.toString()
        ));
        assertRejected(token(
            ISSUER,
            AUDIENCE,
            Instant.now().plusSeconds(60),
            SUBJECT.toString(),
            "not-a-uuid"
        ));
    }

    private void assertRejected(String token) {
        assertThatThrownBy(() -> decoder.decode(token).block())
            .isInstanceOf(JwtException.class);
    }

    private String token(String issuer, String audience, Instant expiresAt) {
        return token(
            issuer,
            audience,
            expiresAt,
            SUBJECT.toString(),
            TENANT.toString()
        );
    }

    private String token(
            String issuer,
            String audience,
            Instant expiresAt,
            String subject,
            String tenantId) {

        Instant now = Instant.now();
        Instant issuedAt = expiresAt.isBefore(now)
            ? expiresAt.minusSeconds(60)
            : now;
        JwtClaimsSet claims = JwtClaimsSet.builder()
            .issuer(issuer)
            .subject(subject)
            .audience(List.of(audience))
            .issuedAt(issuedAt)
            .expiresAt(expiresAt)
            .claim("tenant_id", tenantId)
            .claim("roles", List.of("TENANT_ADMIN"))
            .claim("token_type", "access")
            .build();
        return encoder.encode(JwtEncoderParameters.from(
            JwsHeader.with(SignatureAlgorithm.RS256).build(),
            claims
        )).getTokenValue();
    }

    private byte[] pem(String label, byte[] encoded) {
        String body = java.util.Base64.getMimeEncoder(
            64,
            new byte[] {'\n'}
        ).encodeToString(encoded);
        return ("-----BEGIN " + label + "-----\n"
            + body
            + "\n-----END " + label + "-----\n")
            .getBytes(java.nio.charset.StandardCharsets.US_ASCII);
    }
}
