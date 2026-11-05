package com.ratelimiter.auth.service;

import com.ratelimiter.auth.entity.RefreshTokenEntity;
import com.ratelimiter.auth.exception.InvalidTokenException;
import com.ratelimiter.auth.repository.RefreshTokenRepository;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.security.SecureRandom;
import java.time.Duration;
import java.time.Instant;
import java.util.Base64;
import java.util.HexFormat;
import java.util.UUID;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
public class RefreshTokenService {

    private static final SecureRandom SECURE_RANDOM = new SecureRandom();

    private final RefreshTokenRepository repository;
    private final Duration tokenTtl;

    public RefreshTokenService(
            RefreshTokenRepository repository,
            @Value("${auth.refresh-token.ttl}") Duration tokenTtl) {
        this.repository = repository;
        this.tokenTtl = tokenTtl;
    }

    @Transactional
    public IssuedRefreshToken issue(UUID userId, UUID tenantId) {
        String rawToken = generateToken();
        Instant expiresAt = Instant.now().plus(tokenTtl);
        repository.save(new RefreshTokenEntity(
            UUID.randomUUID(),
            userId,
            tenantId,
            hash(rawToken),
            expiresAt
        ));
        return new IssuedRefreshToken(rawToken, userId, tenantId, expiresAt);
    }

    @Transactional(noRollbackFor = InvalidTokenException.class)
    public IssuedRefreshToken rotate(
            String rawToken,
            UUID expectedUserId,
            UUID targetTenantId) {
        if (rawToken == null || rawToken.isBlank()) {
            throw new InvalidTokenException();
        }

        RefreshTokenEntity current = repository
            .findByTokenHash(hash(rawToken))
            .orElseThrow(InvalidTokenException::new);

        if (expectedUserId != null
                && !expectedUserId.equals(current.getUserId())) {
            throw new InvalidTokenException();
        }

        Instant now = Instant.now();
        if (current.getRevokedAt() != null) {
            repository.revokeAllActiveForUser(current.getUserId());
            throw new InvalidTokenException();
        }
        if (!current.getExpiresAt().isAfter(now)) {
            current.revoke(now);
            throw new InvalidTokenException();
        }

        UUID tenantId = targetTenantId == null
            ? current.getTenantId()
            : targetTenantId;
        current.revoke(now);

        String replacement = generateToken();
        Instant expiresAt = now.plus(tokenTtl);
        repository.save(new RefreshTokenEntity(
            UUID.randomUUID(),
            current.getUserId(),
            tenantId,
            hash(replacement),
            expiresAt
        ));

        return new IssuedRefreshToken(
            replacement,
            current.getUserId(),
            tenantId,
            expiresAt
        );
    }

    @Transactional
    public void revoke(String rawToken) {
        if (rawToken == null || rawToken.isBlank()) {
            return;
        }

        repository.findByTokenHash(hash(rawToken)).ifPresent(token -> {
            if (token.getRevokedAt() == null) {
                token.revoke(Instant.now());
            }
        });
    }

    private String generateToken() {
        byte[] bytes = new byte[32];
        SECURE_RANDOM.nextBytes(bytes);
        return Base64.getUrlEncoder().withoutPadding().encodeToString(bytes);
    }

    private String hash(String token) {
        try {
            byte[] digest = MessageDigest.getInstance("SHA-256")
                .digest(token.getBytes(StandardCharsets.US_ASCII));
            return HexFormat.of().formatHex(digest);
        } catch (NoSuchAlgorithmException exception) {
            throw new IllegalStateException("SHA-256 is unavailable", exception);
        }
    }

    public record IssuedRefreshToken(
        String rawToken,
        UUID userId,
        UUID tenantId,
        Instant expiresAt
    ) {}
}
