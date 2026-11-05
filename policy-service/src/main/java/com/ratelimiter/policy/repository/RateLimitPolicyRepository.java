package com.ratelimiter.policy.repository;

import com.ratelimiter.policy.entity.RateLimitPolicyEntity;
import jakarta.persistence.LockModeType;
import java.util.Optional;
import java.util.UUID;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Lock;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;

public interface RateLimitPolicyRepository
        extends JpaRepository<RateLimitPolicyEntity, UUID> {

    Optional<RateLimitPolicyEntity> findByService_ServiceKeyAndTenantIdAndRouteId(
            String serviceKey,
            String tenantId,
            String routeId
    );

    @Lock(LockModeType.PESSIMISTIC_WRITE)
    @Query("SELECT p FROM RateLimitPolicyEntity p WHERE p.id = :id")
    Optional<RateLimitPolicyEntity> findByIdForUpdate(@Param("id") UUID id);
}
