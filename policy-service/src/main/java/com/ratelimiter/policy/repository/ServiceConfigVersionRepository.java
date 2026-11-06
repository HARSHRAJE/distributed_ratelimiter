package com.ratelimiter.policy.repository;

import com.ratelimiter.policy.entity.ServiceConfigVersionEntity;
import java.util.Optional;
import java.util.UUID;
import org.springframework.data.jpa.repository.JpaRepository;

public interface ServiceConfigVersionRepository
        extends JpaRepository<ServiceConfigVersionEntity, UUID> {

    Optional<ServiceConfigVersionEntity> findByServiceIdAndConfigVersion(
        UUID serviceId,
        Long configVersion
    );
}
