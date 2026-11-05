package com.ratelimiter.policy.redis;

import com.ratelimiter.policy.dto.response.ActivePolicySnapshot;
import com.ratelimiter.policy.entity.PolicyVersionId;
import com.ratelimiter.policy.entity.RateLimitPolicyEntity;
import com.ratelimiter.policy.entity.RateLimitPolicyVersionEntity;
import com.ratelimiter.policy.exception.ResourceNotFoundException;
import com.ratelimiter.policy.repository.RateLimitPolicyRepository;
import com.ratelimiter.policy.repository.RateLimitPolicyVersionRepository;
import java.util.UUID;
import org.springframework.stereotype.Component;
import org.springframework.transaction.annotation.Transactional;

@Component
public class ActivePolicySnapshotBuilder {

    private final RateLimitPolicyRepository policyRepository;
    private final RateLimitPolicyVersionRepository versionRepository;

    public ActivePolicySnapshotBuilder(
            RateLimitPolicyRepository policyRepository,
            RateLimitPolicyVersionRepository versionRepository) {
        this.policyRepository = policyRepository;
        this.versionRepository = versionRepository;
    }

    @Transactional(readOnly = true)
    public ActivePolicySnapshot build(UUID policyId) {
        RateLimitPolicyEntity policy = policyRepository.findById(policyId)
            .orElseThrow(() -> new ResourceNotFoundException(
                "Policy not found: " + policyId
            ));

        Long activeVersion = policy.getActiveVersion();
        if (activeVersion == null) {
            throw new IllegalStateException(
                "Policy has no active version: " + policyId
            );
        }

        RateLimitPolicyVersionEntity version = versionRepository
            .findById(new PolicyVersionId(policyId, activeVersion))
            .orElseThrow(() -> new IllegalStateException(
                "Active version record is missing: " + policyId
            ));

        return new ActivePolicySnapshot(
            policy.getService().getServiceKey(),
            policy.getId(),
            policy.getTenantId(),
            policy.getRouteId(),
            policy.getStatus().name(),
            policy.getSyncRevision(),
            activeVersion,
            version.getTenantCapacity(),
            version.getTenantRefillRate(),
            version.getRouteCapacity(),
            version.getRouteRefillRate(),
            version.getMinRefillRate(),
            version.getMaxRefillRate(),
            version.getSource().name()
        );
    }
}
