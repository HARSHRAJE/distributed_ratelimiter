package com.ratelimiter.auth.repository;

import com.ratelimiter.auth.entity.RefreshTokenEntity;
import jakarta.persistence.LockModeType;
import java.util.List;
import java.util.Optional;
import java.util.UUID;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Lock;
import org.springframework.data.jpa.repository.Modifying;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;

public interface RefreshTokenRepository
        extends JpaRepository<RefreshTokenEntity, UUID> {

    @Lock(LockModeType.PESSIMISTIC_WRITE)
    Optional<RefreshTokenEntity> findByTokenHash(String tokenHash);

    List<RefreshTokenEntity> findByUserIdAndRevokedAtIsNull(UUID userId);

    @Modifying
    @Query("""
        UPDATE RefreshTokenEntity token
        SET token.revokedAt = CURRENT_TIMESTAMP
        WHERE token.userId = :userId
          AND token.revokedAt IS NULL
        """)
    int revokeAllActiveForUser(@Param("userId") UUID userId);
}
