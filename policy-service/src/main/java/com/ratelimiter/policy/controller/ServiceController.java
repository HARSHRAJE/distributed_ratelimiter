
package com.ratelimiter.policy.controller;

import com.ratelimiter.policy.dto.request.CreateServiceRequest;
import com.ratelimiter.policy.dto.request.AdaptiveControlRequest;
import com.ratelimiter.policy.dto.request.AdaptiveServiceUpdateRequest;
import com.ratelimiter.policy.dto.request.AdaptiveServiceRollbackRequest;
import com.ratelimiter.policy.dto.request.ExecutionKillSwitchRequest;
import com.ratelimiter.policy.dto.request.UpdateServiceConfigRequest;
import com.ratelimiter.policy.dto.response.ServiceConfigSnapshot;
import com.ratelimiter.policy.dto.response.ServiceExecutionStatus;
import com.ratelimiter.policy.dto.response.ServiceRollbackStatus;
import com.ratelimiter.policy.dto.response.ExecutionKillSwitchStatus;
import com.ratelimiter.policy.dto.response.ServiceResponse;
import com.ratelimiter.policy.config.PolicyAuthorization;
import com.ratelimiter.policy.redis.RedisServiceConfigReader;
import com.ratelimiter.policy.service.ServiceManagementService;

import jakarta.validation.Valid;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import org.springframework.http.HttpStatus;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.security.access.prepost.PreAuthorize;
import org.springframework.security.oauth2.jwt.Jwt;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.server.ResponseStatusException;
import org.springframework.web.bind.annotation.*;

import java.util.List;
import java.util.UUID;

@RestController
@RequestMapping("/api/v1/services")
public class ServiceController {

    private final ServiceManagementService service;
    private final RedisServiceConfigReader effectiveConfigReader;
    private final String executionApiKey;

    public ServiceController(
            ServiceManagementService service,
            RedisServiceConfigReader effectiveConfigReader,
            @Value("${policy.execution-api-key:}") String executionApiKey) {
        this.service = service;
        this.effectiveConfigReader = effectiveConfigReader;
        this.executionApiKey = executionApiKey;
    }

    @PostMapping
    @ResponseStatus(HttpStatus.CREATED)
    @PreAuthorize("hasRole('SUPER_ADMIN')")
    public ServiceResponse create(
            @Valid @RequestBody CreateServiceRequest request) {
        return service.createService(request);
    }

    @GetMapping
    @PreAuthorize("hasRole('SUPER_ADMIN')")
    public List<ServiceResponse> getAll() {
        return service.getAllServices();
    }

    @GetMapping("/{id}")
    @PreAuthorize("hasAnyRole('SUPER_ADMIN', 'SERVICE_ADMIN')")
    public ServiceResponse getById(
            @PathVariable UUID id,
            @AuthenticationPrincipal Jwt jwt) {
        ServiceResponse response = service.getService(id);
        PolicyAuthorization.requireServiceAccess(jwt, response.serviceKey());
        return response;
    }

    @PutMapping("/{id}/configuration")
    @PreAuthorize("hasRole('SUPER_ADMIN')")
    public ServiceResponse updateConfiguration(
            @PathVariable UUID id,
            @Valid @RequestBody UpdateServiceConfigRequest request) {
        return service.updateConfiguration(id, request);
    }

    @GetMapping("/by-key/{serviceKey}")
    @PreAuthorize("hasAnyRole('SUPER_ADMIN', 'SERVICE_ADMIN')")
    public ServiceResponse getByServiceKey(
            @PathVariable String serviceKey,
            @AuthenticationPrincipal Jwt jwt) {
        PolicyAuthorization.requireServiceAccess(jwt, serviceKey);
        return service.getServiceByKey(serviceKey);
    }

    @PutMapping("/{id}/adaptive-configuration")
    public ServiceResponse updateAdaptiveConfiguration(
            @PathVariable UUID id,
            @RequestHeader(value = "X-Policy-Service-Key", required = false)
                String suppliedKey,
            @Valid @RequestBody AdaptiveServiceUpdateRequest request) {
        requireExecutionApiKey(suppliedKey);
        return service.updateConfigurationByExecution(id, request);
    }

    @GetMapping("/{id}/configuration/executions/{executionId}")
    public ServiceExecutionStatus getExecutionStatus(
            @PathVariable UUID id,
            @PathVariable UUID executionId,
            @RequestHeader(value = "X-Policy-Service-Key", required = false)
                String suppliedKey) {
        requireExecutionApiKey(suppliedKey);
        return service.getExecutionStatus(id, executionId);
    }

    @PutMapping("/{id}/adaptive-rollback")
    public ServiceRollbackStatus rollbackAdaptiveConfiguration(
            @PathVariable UUID id,
            @RequestHeader(value = "X-Policy-Service-Key", required = false)
                String suppliedKey,
            @Valid @RequestBody AdaptiveServiceRollbackRequest request) {
        requireExecutionApiKey(suppliedKey);
        return service.rollbackConfigurationByExecution(id, request);
    }

    @GetMapping("/{id}/configuration/rollbacks/{rollbackId}")
    public ServiceRollbackStatus getRollbackStatus(
            @PathVariable UUID id,
            @PathVariable UUID rollbackId,
            @RequestHeader(value = "X-Policy-Service-Key", required = false)
                String suppliedKey) {
        requireExecutionApiKey(suppliedKey);
        ServiceRollbackStatus status =
            service.getRollbackStatus(id, rollbackId);
        if (status == null) {
            throw new ResponseStatusException(
                HttpStatus.NOT_FOUND,
                "Rollback request not found"
            );
        }
        return status;
    }

    @PutMapping("/by-key/{serviceKey}/adaptive-control")
    public ServiceResponse setAdaptiveControl(
            @PathVariable String serviceKey,
            @RequestHeader(value = "X-Policy-Service-Key", required = false)
                String suppliedKey,
            @Valid @RequestBody AdaptiveControlRequest request) {
        requireExecutionApiKey(suppliedKey);
        return service.setAdaptiveControl(serviceKey, request);
    }

    @PutMapping("/execution-control")
    public ExecutionKillSwitchStatus setExecutionKillSwitch(
            @RequestHeader(value = "X-Policy-Service-Key", required = false)
                String suppliedKey,
            @Valid @RequestBody ExecutionKillSwitchRequest request) {
        requireExecutionApiKey(suppliedKey);
        return new ExecutionKillSwitchStatus(
            service.setExecutionKillSwitch(request.active())
        );
    }

    @GetMapping("/by-key/{serviceKey}/effective-configuration")
    public ServiceConfigSnapshot getEffectiveConfiguration(
            @PathVariable String serviceKey,
            @RequestHeader(value = "X-Policy-Service-Key", required = false)
                String suppliedKey) {
        requireExecutionApiKey(suppliedKey);
        return effectiveConfigReader.get(serviceKey).orElseThrow(
            () -> new ResponseStatusException(
                HttpStatus.NOT_FOUND,
                "Effective service configuration is not available"
            )
        );
    }

    private void requireExecutionApiKey(String suppliedKey) {
        if (executionApiKey.length() < 32) {
            throw new ResponseStatusException(
                HttpStatus.SERVICE_UNAVAILABLE,
                "Policy execution authentication is not configured"
            );
        }
        if (suppliedKey == null || !MessageDigest.isEqual(
                executionApiKey.getBytes(StandardCharsets.UTF_8),
                suppliedKey.getBytes(StandardCharsets.UTF_8))) {
            throw new ResponseStatusException(
                HttpStatus.UNAUTHORIZED,
                "Unauthorized"
            );
        }
    }
}
