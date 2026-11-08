package com.ratelimiter.auth.controller;

import com.ratelimiter.auth.dto.AdminBootstrapRequest;
import com.ratelimiter.auth.dto.AdminBootstrapResponse;
import com.ratelimiter.auth.dto.AdminCreateUserRequest;
import com.ratelimiter.auth.dto.AdminUserResponse;
import com.ratelimiter.auth.dto.CreateMembershipRequest;
import com.ratelimiter.auth.dto.CreateTenantRequest;
import com.ratelimiter.auth.dto.MembershipResponse;
import com.ratelimiter.auth.dto.TenantResponse;
import com.ratelimiter.auth.service.AdminProvisioningService;
import jakarta.validation.Valid;
import java.util.UUID;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.security.access.prepost.PreAuthorize;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/v1/auth/admin")
public class AdminProvisioningController {

    private final AdminProvisioningService provisioningService;

    public AdminProvisioningController(
            AdminProvisioningService provisioningService) {
        this.provisioningService = provisioningService;
    }

    @PostMapping("/bootstrap")
    public ResponseEntity<AdminBootstrapResponse> bootstrap(
            @RequestHeader("X-Admin-Bootstrap-Token") String bootstrapToken,
            @Valid @RequestBody AdminBootstrapRequest request) {
        return ResponseEntity.status(HttpStatus.CREATED).body(
            provisioningService.bootstrap(bootstrapToken, request)
        );
    }

    @PostMapping("/tenants")
    @PreAuthorize("hasRole('SUPER_ADMIN')")
    public ResponseEntity<TenantResponse> createTenant(
            @Valid @RequestBody CreateTenantRequest request) {
        return ResponseEntity.status(HttpStatus.CREATED).body(
            provisioningService.createTenant(request)
        );
    }

    @PostMapping("/tenants/{tenantId}/memberships")
    @PreAuthorize("hasRole('SUPER_ADMIN')")
    public ResponseEntity<MembershipResponse> addMembership(
            @PathVariable UUID tenantId,
            @Valid @RequestBody CreateMembershipRequest request) {
        return ResponseEntity.status(HttpStatus.CREATED).body(
            provisioningService.addMembership(tenantId, request)
        );
    }

    @PostMapping("/tenants/{tenantId}/users")
    @PreAuthorize("hasRole('SUPER_ADMIN')")
    public ResponseEntity<AdminUserResponse> createUser(
            @PathVariable UUID tenantId,
            @Valid @RequestBody AdminCreateUserRequest request) {
        return ResponseEntity.status(HttpStatus.CREATED).body(
            provisioningService.createUser(tenantId, request)
        );
    }
}
