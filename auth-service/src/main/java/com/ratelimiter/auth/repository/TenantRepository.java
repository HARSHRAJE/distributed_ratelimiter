package com.ratelimiter.auth.repository;

import com.ratelimiter.auth.entity.TenantEntity;
import java.util.UUID;
import org.springframework.data.jpa.repository.JpaRepository;

public interface TenantRepository extends JpaRepository<TenantEntity, UUID> {

    boolean existsByTenantKey(String tenantKey);
}
