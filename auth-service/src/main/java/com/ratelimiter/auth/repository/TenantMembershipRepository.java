package com.ratelimiter.auth.repository;

import com.ratelimiter.auth.entity.TenantMembershipEntity;
import java.util.List;
import java.util.Optional;
import java.util.UUID;
import org.springframework.data.jpa.repository.JpaRepository;

public interface TenantMembershipRepository
        extends JpaRepository<TenantMembershipEntity, UUID> {

    Optional<TenantMembershipEntity> findByUserIdAndTenantId(
        UUID userId,
        UUID tenantId
    );

    boolean existsByRole(String role);

    List<TenantMembershipEntity> findByUserId(UUID userId);
}
