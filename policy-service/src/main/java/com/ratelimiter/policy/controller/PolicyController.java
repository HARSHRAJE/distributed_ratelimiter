package com.ratelimiter.policy.controller;

import com.ratelimiter.policy.dto.request.CreatePolicyRequest;
import com.ratelimiter.policy.dto.request.RollbackPolicyRequest;
import com.ratelimiter.policy.dto.request.UpdatePolicyRequest;
import com.ratelimiter.policy.dto.response.PolicyResponse;
import com.ratelimiter.policy.dto.response.PolicyAuditResponse;
import com.ratelimiter.policy.dto.response.PolicyVersionResponse;
import com.ratelimiter.policy.service.PolicyManagementService;
import com.ratelimiter.policy.config.PolicyAuthorization;

import jakarta.validation.Valid;

import java.util.List;
import java.util.UUID;

import org.springframework.security.access.prepost.PreAuthorize;
import org.springframework.security.oauth2.jwt.Jwt;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/api/v1/policies")
public class PolicyController {

    private final PolicyManagementService policyManagementService;

    public PolicyController(
            PolicyManagementService policyManagementService) {
        this.policyManagementService = policyManagementService;
    }

    @PostMapping
    @ResponseStatus(HttpStatus.CREATED)
    @PreAuthorize("hasAnyRole('SUPER_ADMIN', 'SERVICE_ADMIN')")
    public PolicyResponse createPolicy(
            @Valid @RequestBody CreatePolicyRequest request,
            @AuthenticationPrincipal Jwt jwt) {

        PolicyAuthorization.requireServiceAccess(jwt, request.serviceKey());
        return policyManagementService.createPolicy(new CreatePolicyRequest(
            request.serviceKey(),
            request.tenantId(),
            request.routeId(),
            request.tenantCapacity(),
            request.tenantRefillRate(),
            request.routeCapacity(),
            request.routeRefillRate(),
            request.minRefillRate(),
            request.maxRefillRate(),
            PolicyAuthorization.actorId(jwt)
        ));
    }

    @PutMapping("/{policyId}")
    @PreAuthorize("hasAnyRole('SUPER_ADMIN', 'SERVICE_ADMIN')")
    public PolicyResponse updatePolicy(
            @PathVariable UUID policyId,
            @Valid @RequestBody UpdatePolicyRequest request,
            @AuthenticationPrincipal Jwt jwt) {

        PolicyAuthorization.requireServiceAccess(
            jwt,
            policyManagementService.getPolicy(policyId).serviceKey()
        );
        return policyManagementService.updatePolicy(
            policyId,
            new UpdatePolicyRequest(
                request.expectedActiveVersion(),
                request.tenantCapacity(),
                request.tenantRefillRate(),
                request.routeCapacity(),
                request.routeRefillRate(),
                request.minRefillRate(),
                request.maxRefillRate(),
                PolicyAuthorization.actorId(jwt)
            )
        );
    }

    @PostMapping("/{policyId}/rollback/{version}")
    @PreAuthorize("hasAnyRole('SUPER_ADMIN', 'SERVICE_ADMIN')")
    public PolicyResponse rollbackPolicy(
            @PathVariable UUID policyId,
            @PathVariable Long version,
            @Valid @RequestBody RollbackPolicyRequest request,
            @AuthenticationPrincipal Jwt jwt) {

        PolicyAuthorization.requireServiceAccess(
            jwt,
            policyManagementService.getPolicy(policyId).serviceKey()
        );
        return policyManagementService.rollbackPolicy(
            policyId,
            version,
            new RollbackPolicyRequest(
                request.expectedActiveVersion(),
                PolicyAuthorization.actorId(jwt)
            )
        );
    }

    @PatchMapping("/{policyId}/activate")
    @ResponseStatus(HttpStatus.NO_CONTENT)
    @PreAuthorize("hasAnyRole('SUPER_ADMIN', 'SERVICE_ADMIN')")
    public void activatePolicy(
            @PathVariable UUID policyId,
            @AuthenticationPrincipal Jwt jwt) {
        PolicyResponse policy = policyManagementService.getPolicy(policyId);
        PolicyAuthorization.requireServiceAccess(jwt, policy.serviceKey());
        policyManagementService.activatePolicy(
            policyId,
            PolicyAuthorization.actorId(jwt)
        );
    }

    @PatchMapping("/{policyId}/deactivate")
    @ResponseStatus(HttpStatus.NO_CONTENT)
    @PreAuthorize("hasAnyRole('SUPER_ADMIN', 'SERVICE_ADMIN')")
    public void deactivatePolicy(
            @PathVariable UUID policyId,
            @AuthenticationPrincipal Jwt jwt) {
        PolicyResponse policy = policyManagementService.getPolicy(policyId);
        PolicyAuthorization.requireServiceAccess(jwt, policy.serviceKey());
        policyManagementService.deactivatePolicy(
            policyId,
            PolicyAuthorization.actorId(jwt)
        );
    }

    @GetMapping("/{policyId}")
    @PreAuthorize("hasAnyRole('SUPER_ADMIN', 'SERVICE_ADMIN', 'TENANT_ADMIN')")
    public PolicyResponse getPolicy(
            @PathVariable UUID policyId,
            @AuthenticationPrincipal Jwt jwt) {

        PolicyResponse policy = policyManagementService.getPolicy(policyId);
        PolicyAuthorization.requirePolicyRead(jwt, policy);
        return policy;
    }

    @GetMapping
    @PreAuthorize("hasAnyRole('SUPER_ADMIN', 'SERVICE_ADMIN', 'TENANT_ADMIN')")
    public PolicyResponse getPolicyByScope(
            @RequestParam String serviceKey,
            @RequestParam String tenantId,
            @RequestParam String routeId,
            @AuthenticationPrincipal Jwt jwt) {

        PolicyAuthorization.requireTenantOrServiceRead(
            jwt,
            serviceKey,
            tenantId
        );
        return policyManagementService.getPolicy(
            serviceKey, tenantId, routeId
        );
    }

    @GetMapping("/{policyId}/versions")
    @PreAuthorize("hasAnyRole('SUPER_ADMIN', 'SERVICE_ADMIN', 'TENANT_ADMIN')")
    public List<PolicyVersionResponse> getPolicyVersions(
            @PathVariable UUID policyId,
            @AuthenticationPrincipal Jwt jwt) {

        PolicyAuthorization.requirePolicyRead(
            jwt,
            policyManagementService.getPolicy(policyId)
        );
        return policyManagementService.getPolicyVersions(policyId);
    }

    @GetMapping("/{policyId}/audit")
    @PreAuthorize("hasAnyRole('SUPER_ADMIN', 'SERVICE_ADMIN', 'TENANT_ADMIN')")
    public List<PolicyAuditResponse> getAuditHistory(
            @PathVariable UUID policyId,
            @AuthenticationPrincipal Jwt jwt) {

        PolicyAuthorization.requirePolicyRead(
            jwt,
            policyManagementService.getPolicy(policyId)
        );
        return policyManagementService.getAuditHistory(policyId);
    }

    @GetMapping("/{policyId}/versions/{version}")
    @PreAuthorize("hasAnyRole('SUPER_ADMIN', 'SERVICE_ADMIN', 'TENANT_ADMIN')")
    public PolicyVersionResponse getPolicyVersion(
            @PathVariable UUID policyId,
            @PathVariable Long version,
            @AuthenticationPrincipal Jwt jwt) {

        PolicyAuthorization.requirePolicyRead(
            jwt,
            policyManagementService.getPolicy(policyId)
        );
        return policyManagementService.getPolicyVersion(
            policyId, version
        );
    }
}