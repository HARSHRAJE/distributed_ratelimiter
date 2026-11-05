package com.ratelimiter.policy.controller;

import com.ratelimiter.policy.dto.request.CreatePolicyRequest;
import com.ratelimiter.policy.dto.request.RollbackPolicyRequest;
import com.ratelimiter.policy.dto.request.UpdatePolicyRequest;
import com.ratelimiter.policy.dto.response.PolicyResponse;
import com.ratelimiter.policy.dto.response.PolicyAuditResponse;
import com.ratelimiter.policy.dto.response.PolicyVersionResponse;
import com.ratelimiter.policy.service.PolicyManagementService;

import jakarta.validation.Valid;

import java.util.List;
import java.util.UUID;

import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.RequestHeader;
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
    public PolicyResponse createPolicy(
            @Valid @RequestBody CreatePolicyRequest request) {

        return policyManagementService.createPolicy(request);
    }

    @PutMapping("/{policyId}")
    public PolicyResponse updatePolicy(
            @PathVariable UUID policyId,
            @Valid @RequestBody UpdatePolicyRequest request) {

        return policyManagementService.updatePolicy(
            policyId,
            request
        );
    }

    @PostMapping("/{policyId}/rollback/{version}")
    public PolicyResponse rollbackPolicy(
            @PathVariable UUID policyId,
            @PathVariable Long version,
            @Valid @RequestBody RollbackPolicyRequest request) {

        return policyManagementService.rollbackPolicy(
            policyId, version, request
        );
    }

    @PatchMapping("/{policyId}/activate")
    @ResponseStatus(HttpStatus.NO_CONTENT)
    public void activatePolicy(
            @PathVariable UUID policyId,
            @RequestHeader("X-Actor-Id") String actor) {
        policyManagementService.activatePolicy(policyId, actor);
    }

    @PatchMapping("/{policyId}/deactivate")
    @ResponseStatus(HttpStatus.NO_CONTENT)
    public void deactivatePolicy(
            @PathVariable UUID policyId,
            @RequestHeader("X-Actor-Id") String actor) {
        policyManagementService.deactivatePolicy(policyId, actor);
    }

    @GetMapping("/{policyId}")
    public PolicyResponse getPolicy(
            @PathVariable UUID policyId) {

        return policyManagementService.getPolicy(policyId);
    }

    @GetMapping
    public PolicyResponse getPolicyByScope(
            @RequestParam String serviceKey,
            @RequestParam String tenantId,
            @RequestParam String routeId) {

        return policyManagementService.getPolicy(
            serviceKey, tenantId, routeId
        );
    }

    @GetMapping("/{policyId}/versions")
    public List<PolicyVersionResponse> getPolicyVersions(
            @PathVariable UUID policyId) {

        return policyManagementService.getPolicyVersions(policyId);
    }

    @GetMapping("/{policyId}/audit")
    public List<PolicyAuditResponse> getAuditHistory(
            @PathVariable UUID policyId) {

        return policyManagementService.getAuditHistory(policyId);
    }

    @GetMapping("/{policyId}/versions/{version}")
    public PolicyVersionResponse getPolicyVersion(
            @PathVariable UUID policyId,
            @PathVariable Long version) {

        return policyManagementService.getPolicyVersion(
            policyId, version
        );
    }
}