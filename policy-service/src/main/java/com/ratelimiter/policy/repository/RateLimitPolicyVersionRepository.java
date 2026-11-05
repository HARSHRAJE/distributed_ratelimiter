package com.ratelimiter.policy.repository;

import com.ratelimiter.policy.entity.PolicyVersionId;
import com.ratelimiter.policy.entity.RateLimitPolicyVersionEntity;
import java.util.List;
import java.util.Optional;
import java.util.UUID;
import org.springframework.data.jpa.repository.JpaRepository;

public interface RateLimitPolicyVersionRepository
        extends JpaRepository<RateLimitPolicyVersionEntity, PolicyVersionId> {

    List<RateLimitPolicyVersionEntity> findByIdPolicyIdOrderByIdVersionDesc(UUID policyId);

    Optional<RateLimitPolicyVersionEntity> findByIdPolicyIdAndIdVersion(
        UUID policyId,
        Long version
    );
}
