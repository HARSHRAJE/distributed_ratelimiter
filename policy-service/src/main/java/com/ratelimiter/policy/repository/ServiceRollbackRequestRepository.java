package com.ratelimiter.policy.repository;

import com.ratelimiter.policy.entity.ServiceRollbackRequestEntity;
import java.util.UUID;
import org.springframework.data.jpa.repository.JpaRepository;

public interface ServiceRollbackRequestRepository
        extends JpaRepository<ServiceRollbackRequestEntity, UUID> {}
