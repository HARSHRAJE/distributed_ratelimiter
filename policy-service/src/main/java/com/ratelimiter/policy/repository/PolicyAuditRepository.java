package com.ratelimiter.policy.repository;

import com.ratelimiter.policy.entity.PolicyAuditEntity;
import java.util.List;
import java.util.UUID;
import org.springframework.data.jpa.repository.JpaRepository;

public interface PolicyAuditRepository
        extends JpaRepository<PolicyAuditEntity, UUID> {

    List<PolicyAuditEntity> findByPolicyIdOrderByOccurredAtDesc(UUID policyId);
}
