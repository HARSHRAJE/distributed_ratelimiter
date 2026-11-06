package com.ratelimiter.policy.repository;

import com.ratelimiter.policy.entity.ServiceExecutionRequestEntity;
import java.util.UUID;
import org.springframework.data.jpa.repository.JpaRepository;

public interface ServiceExecutionRequestRepository
        extends JpaRepository<ServiceExecutionRequestEntity, UUID> {}
