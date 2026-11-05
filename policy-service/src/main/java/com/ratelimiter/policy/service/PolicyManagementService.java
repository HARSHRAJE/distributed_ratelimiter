package com.ratelimiter.policy.service;

import com.ratelimiter.policy.dto.request.CreatePolicyRequest;
import com.ratelimiter.policy.dto.request.RollbackPolicyRequest;
import com.ratelimiter.policy.dto.request.UpdatePolicyRequest;
import com.ratelimiter.policy.dto.response.PolicyResponse;
import com.ratelimiter.policy.dto.response.PolicyAuditResponse;
import com.ratelimiter.policy.dto.response.PolicyVersionResponse;
import com.ratelimiter.policy.entity.*;
import com.ratelimiter.policy.exception.DuplicateResourceException;
import com.ratelimiter.policy.exception.PolicyConflictException;
import com.ratelimiter.policy.exception.PolicyVersionConflictException;
import com.ratelimiter.policy.exception.ResourceNotFoundException;
import com.ratelimiter.policy.repository.*;

import java.math.BigDecimal;
import java.util.List;
import java.util.UUID;

import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;


@Service
public class PolicyManagementService {

    private final ServiceRepository serviceRepository;
    private final RateLimitPolicyRepository policyRepository;
    private final RateLimitPolicyVersionRepository versionRepository;
    private final PolicyAuditRepository auditRepository;
    private final OutboxService outboxService;

    public PolicyManagementService(
            ServiceRepository serviceRepository,
            RateLimitPolicyRepository policyRepository,
            RateLimitPolicyVersionRepository versionRepository,
            PolicyAuditRepository auditRepository,
            OutboxService outboxService) {

        this.serviceRepository = serviceRepository;
        this.policyRepository = policyRepository;
        this.versionRepository = versionRepository;
        this.auditRepository = auditRepository;
        this.outboxService = outboxService;
    }

    private void recordAudit(
            UUID policyId,
            PolicyAuditAction action,
            Long previousVersion,
            Long newVersion,
            String actor,
            String reason) {

        PolicyAuditEntity audit = new PolicyAuditEntity();
        audit.setPolicyId(policyId);
        audit.setAction(action);
        audit.setPreviousVersion(previousVersion);
        audit.setNewVersion(newVersion);
        audit.setActor(actor);
        audit.setReason(reason);

        auditRepository.save(audit);
    }

    private PolicyVersionResponse toVersionResponse(
        RateLimitPolicyVersionEntity version) {

        return new PolicyVersionResponse(
            version.getId().getVersion(),
            version.getTenantCapacity(),
            version.getTenantRefillRate(),
            version.getRouteCapacity(),
            version.getRouteRefillRate(),
            version.getMinRefillRate(),
            version.getMaxRefillRate(),
            version.getSource().name(),
            version.getCreatedBy(),
            version.getCreatedAt()
        );
    }


    @Transactional(readOnly = true)
    public PolicyResponse getPolicy(UUID policyId) {

        RateLimitPolicyEntity policy = policyRepository
            .findById(policyId)
            .orElseThrow(() -> new ResourceNotFoundException(
                "Policy not found: " + policyId
            ));

        return getActivePolicyResponse(policy);
    }

    @Transactional(readOnly = true)
    public PolicyResponse getPolicy(
            String serviceKey,
            String tenantId,
            String routeId) {

        RateLimitPolicyEntity policy = policyRepository
            .findByService_ServiceKeyAndTenantIdAndRouteId(
                serviceKey, tenantId, routeId
            )
            .orElseThrow(() -> new ResourceNotFoundException(
                "Policy not found for the supplied service, tenant and route"
            ));

        return getActivePolicyResponse(policy);
    }

    private PolicyResponse getActivePolicyResponse(
        RateLimitPolicyEntity policy) {

        if (policy.getActiveVersion() == null) {
            throw new IllegalStateException(
                "Policy has no active version: " + policy.getId()
            );
        }

        RateLimitPolicyVersionEntity version =
            versionRepository.findById(
                new PolicyVersionId(
                    policy.getId(),
                    policy.getActiveVersion()
                )
            ).orElseThrow(() -> new IllegalStateException(
                "Active policy version record is missing"
            ));

        return toResponse(policy, version);
    }

    @Transactional(readOnly = true)
    public List<PolicyVersionResponse> getPolicyVersions(UUID policyId) {

        if (!policyRepository.existsById(policyId)) {
            throw new ResourceNotFoundException(
                "Policy not found: " + policyId
            );
        }

        return versionRepository
            .findByIdPolicyIdOrderByIdVersionDesc(policyId)
            .stream()
            .map(this::toVersionResponse)
            .toList();
    }

    @Transactional(readOnly = true)
    public PolicyVersionResponse getPolicyVersion(
            UUID policyId,
            Long versionNumber) {

        return versionRepository
            .findByIdPolicyIdAndIdVersion(policyId, versionNumber)
            .map(this::toVersionResponse)
            .orElseThrow(() -> new ResourceNotFoundException(
                "Policy version not found: " + versionNumber
            ));
    }

    @Transactional(readOnly = true)
    public List<PolicyAuditResponse> getAuditHistory(UUID policyId) {

        if (!policyRepository.existsById(policyId)) {
            throw new ResourceNotFoundException(
                "Policy not found: " + policyId
            );
        }

        return auditRepository
            .findByPolicyIdOrderByOccurredAtDesc(policyId)
            .stream()
            .map(audit -> new PolicyAuditResponse(
                audit.getId(),
                audit.getPolicyId(),
                audit.getAction().name(),
                audit.getPreviousVersion(),
                audit.getNewVersion(),
                audit.getActor(),
                audit.getReason(),
                audit.getOccurredAt()
            ))
            .toList();
    }

    @Transactional
    public PolicyResponse updatePolicy(
            UUID policyId,
            UpdatePolicyRequest request) {

        RateLimitPolicyEntity policy = policyRepository
            .findByIdForUpdate(policyId)
            .orElseThrow(() -> new ResourceNotFoundException(
                "Policy not found: " + policyId
            ));

        if (!request.expectedActiveVersion().equals(
                policy.getActiveVersion())) {

            throw new PolicyVersionConflictException(
                "Policy has changed. Expected version: "
                + request.expectedActiveVersion()
                + ", current version: "
                + policy.getActiveVersion()
            );
        }

        if (policy.getStatus() != PolicyStatus.ACTIVE) {
            throw new PolicyConflictException(
                "Cannot update a disabled policy. Activate it first."
            );
        }

        validatePolicyRates(
            policy.getService(),
            request.tenantRefillRate(),
            request.routeRefillRate(),
            request.minRefillRate(),
            request.maxRefillRate()
        );

        if (policy.getActiveVersion() == null) {
            throw new IllegalStateException(
                "Policy has no active version: " + policyId
            );
        }

        RateLimitPolicyVersionEntity currentVersion =
            versionRepository.findById(
                new PolicyVersionId(
                    policy.getId(),
                    policy.getActiveVersion()
                )
            ).orElseThrow(() -> new IllegalStateException(
                "Active policy version is missing"
            ));

        Long previousVersion = currentVersion.getId().getVersion();
        Long nextVersion = previousVersion + 1;

        RateLimitPolicyVersionEntity newVersion =
            new RateLimitPolicyVersionEntity();

        newVersion.setId(
            new PolicyVersionId(policy.getId(), nextVersion)
        );

        newVersion.setPolicy(policy);
        newVersion.setTenantCapacity(request.tenantCapacity());
        newVersion.setTenantRefillRate(request.tenantRefillRate());
        newVersion.setRouteCapacity(request.routeCapacity());
        newVersion.setRouteRefillRate(request.routeRefillRate());
        newVersion.setMinRefillRate(request.minRefillRate());
        newVersion.setMaxRefillRate(request.maxRefillRate());
        newVersion.setSource(PolicySource.MANUAL);
        newVersion.setCreatedBy(request.createdBy());

        versionRepository.saveAndFlush(newVersion);

        policy.setActiveVersion(nextVersion);
        advanceSyncRevision(policy);
        policyRepository.saveAndFlush(policy);

        recordAudit(
            policy.getId(),
            PolicyAuditAction.UPDATED,
            previousVersion,
            nextVersion,
            request.createdBy(),
            "Policy updated manually"
        );

        outboxService.publishPolicyReconciliation(
            policy.getId(),
            "UPDATED"
        );

        return toResponse(policy, newVersion);
    }

    @Transactional
    public PolicyResponse rollbackPolicy(
            UUID policyId,
            Long targetVersion,
            RollbackPolicyRequest request) {

        RateLimitPolicyEntity policy = policyRepository
            .findByIdForUpdate(policyId)
            .orElseThrow(() -> new ResourceNotFoundException(
                "Policy not found: " + policyId
            ));

        if (!request.expectedActiveVersion().equals(
                policy.getActiveVersion())) {

            throw new PolicyVersionConflictException(
                "Policy has changed. Expected version: "
                + request.expectedActiveVersion()
                + ", current version: "
                + policy.getActiveVersion()
            );
        }

        if (policy.getStatus() != PolicyStatus.ACTIVE) {
            throw new PolicyConflictException(
                "Cannot rollback a disabled policy. Activate it first."
            );
        }

        if (policy.getActiveVersion() == null) {
            throw new IllegalStateException(
                "Policy has no active version: " + policyId
            );
        }

        if (targetVersion >= policy.getActiveVersion()) {
            throw new IllegalArgumentException(
                "Rollback target must be an older policy version"
            );
        }

        RateLimitPolicyVersionEntity target =
            versionRepository.findById(
                new PolicyVersionId(policyId, targetVersion)
            ).orElseThrow(() -> new ResourceNotFoundException(
                "Target version not found: " + targetVersion
            ));

        validatePolicyRates(
            policy.getService(),
            target.getTenantRefillRate(),
            target.getRouteRefillRate(),
            target.getMinRefillRate(),
            target.getMaxRefillRate()
        );

        Long previousVersion = policy.getActiveVersion();
        Long nextVersion = previousVersion + 1;

        RateLimitPolicyVersionEntity rollbackVersion =
            new RateLimitPolicyVersionEntity();

        rollbackVersion.setId(
            new PolicyVersionId(policyId, nextVersion)
        );

        rollbackVersion.setPolicy(policy);
        rollbackVersion.setTenantCapacity(target.getTenantCapacity());
        rollbackVersion.setTenantRefillRate(target.getTenantRefillRate());
        rollbackVersion.setRouteCapacity(target.getRouteCapacity());
        rollbackVersion.setRouteRefillRate(target.getRouteRefillRate());
        rollbackVersion.setMinRefillRate(target.getMinRefillRate());
        rollbackVersion.setMaxRefillRate(target.getMaxRefillRate());
        rollbackVersion.setSource(PolicySource.ROLLBACK);
        rollbackVersion.setCreatedBy(request.createdBy());

        versionRepository.saveAndFlush(rollbackVersion);

        policy.setActiveVersion(nextVersion);
        advanceSyncRevision(policy);
        policyRepository.saveAndFlush(policy);

        recordAudit(
            policyId,
            PolicyAuditAction.ROLLED_BACK,
            previousVersion,
            nextVersion,
            request.createdBy(),
            "Rollback to version " + targetVersion
        );

        outboxService.publishPolicyReconciliation(
            policyId,
            "ROLLED_BACK"
        );

        return toResponse(policy, rollbackVersion);
    }

    @Transactional
    public void activatePolicy(UUID policyId, String actor) {

        RateLimitPolicyEntity policy = policyRepository
            .findByIdForUpdate(policyId)
            .orElseThrow(() -> new ResourceNotFoundException(
                "Policy not found: " + policyId
            ));

        if (policy.getActiveVersion() == null) {
            throw new IllegalStateException(
                "Cannot activate policy without an active version"
            );
        }

        Long currentVersion = policy.getActiveVersion();
        policy.setStatus(PolicyStatus.ACTIVE);
        advanceSyncRevision(policy);
        policyRepository.save(policy);
        recordAudit(
            policyId,
            PolicyAuditAction.ACTIVATED,
            currentVersion,
            currentVersion,
            actor,
            null
        );
        outboxService.publishPolicyReconciliation(
            policyId,
            "ACTIVATED"
        );
    }

    @Transactional
    public void deactivatePolicy(UUID policyId, String actor) {

        RateLimitPolicyEntity policy = policyRepository
            .findByIdForUpdate(policyId)
            .orElseThrow(() -> new ResourceNotFoundException(
                "Policy not found: " + policyId
            ));

        Long currentVersion = policy.getActiveVersion();
        policy.setStatus(PolicyStatus.DISABLED);
        advanceSyncRevision(policy);
        policyRepository.save(policy);
        recordAudit(
            policyId,
            PolicyAuditAction.DEACTIVATED,
            currentVersion,
            currentVersion,
            actor,
            null
        );
        outboxService.publishPolicyReconciliation(
            policyId,
            "DEACTIVATED"
        );
    }

    @Transactional
    public PolicyResponse createPolicy(CreatePolicyRequest request) {

        // 1. Find registered service
        ServiceEntity service = serviceRepository
            .findByServiceKey(request.serviceKey())
            .orElseThrow(() -> new IllegalArgumentException(
                "Service not found: " + request.serviceKey()
            ));

        validatePolicyRates(
            service,
            request.tenantRefillRate(),
            request.routeRefillRate(),
            request.minRefillRate(),
            request.maxRefillRate()
        );

        // 3. Check duplicate policy
        boolean exists = policyRepository
            .findByService_ServiceKeyAndTenantIdAndRouteId(
                request.serviceKey(),
                request.tenantId(),
                request.routeId()
            ).isPresent();

        if (exists) {
            throw new DuplicateResourceException(
                "Policy already exists for this service, tenant and route"
            );
        }

        // 4. Create policy
        RateLimitPolicyEntity policy = new RateLimitPolicyEntity();

        policy.setService(service);
        policy.setTenantId(request.tenantId());
        policy.setRouteId(request.routeId());
        policy.setStatus(PolicyStatus.ACTIVE);
        policy.setActiveVersion(null);

        // Save first to obtain generated UUID
        policy = policyRepository.saveAndFlush(policy);

        // 5. Create initial policy version
        Long versionNumber = 1L;

        RateLimitPolicyVersionEntity version =
            new RateLimitPolicyVersionEntity();

        version.setId(
            new PolicyVersionId(policy.getId(), versionNumber)
        );

        version.setPolicy(policy);
        version.setTenantCapacity(request.tenantCapacity());
        version.setTenantRefillRate(request.tenantRefillRate());
        version.setRouteCapacity(request.routeCapacity());
        version.setRouteRefillRate(request.routeRefillRate());
        version.setMinRefillRate(request.minRefillRate());
        version.setMaxRefillRate(request.maxRefillRate());
        version.setSource(PolicySource.MANUAL);
        version.setCreatedBy(request.createdBy());

        versionRepository.save(version);

        // 6. Activate version 1
        policy.setActiveVersion(versionNumber);

        policyRepository.save(policy);

        recordAudit(
            policy.getId(),
            PolicyAuditAction.CREATED,
            null,
            versionNumber,
            request.createdBy(),
            "Initial policy creation"
        );

        outboxService.publishPolicyReconciliation(
            policy.getId(),
            "CREATED"
        );

        // 7. Return response
        return toResponse(policy, version);
    }

    private void validatePolicyRates(
            ServiceEntity service,
            BigDecimal tenantRefillRate,
            BigDecimal routeRefillRate,
            BigDecimal minRefillRate,
            BigDecimal maxRefillRate) {

        BigDecimal hardMax = service.getHardMaxRefillRate();

        if (tenantRefillRate.compareTo(hardMax) > 0) {
            throw new IllegalArgumentException(
                "Tenant refill rate exceeds service hard maximum"
            );
        }

        if (routeRefillRate.compareTo(hardMax) > 0) {
            throw new IllegalArgumentException(
                "Route refill rate exceeds service hard maximum"
            );
        }

        if (maxRefillRate.compareTo(hardMax) > 0) {
            throw new IllegalArgumentException(
                "Maximum route refill rate exceeds service hard maximum"
            );
        }

        if (minRefillRate.compareTo(routeRefillRate) > 0 ||
            routeRefillRate.compareTo(maxRefillRate) > 0) {

            throw new IllegalArgumentException(
                "Route refill rate must be between minimum and maximum"
            );
        }
    }

    private void advanceSyncRevision(RateLimitPolicyEntity policy) {
        policy.setSyncRevision(
            Math.incrementExact(policy.getSyncRevision())
        );
    }

    private PolicyResponse toResponse(
            RateLimitPolicyEntity policy,
            RateLimitPolicyVersionEntity version) {

        return new PolicyResponse(
            policy.getId(),
            policy.getService().getServiceKey(),
            policy.getTenantId(),
            policy.getRouteId(),
            policy.getActiveVersion(),
            policy.getStatus().name(),
            version.getTenantCapacity(),
            version.getTenantRefillRate(),
            version.getRouteCapacity(),
            version.getRouteRefillRate(),
            version.getMinRefillRate(),
            version.getMaxRefillRate(),
            version.getSource().name(),
            version.getCreatedBy(),
            version.getCreatedAt()
        );
    }
}