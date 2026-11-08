package com.ratelimiter.auth.controller;

import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import com.ratelimiter.auth.config.SecurityConfig;
import com.ratelimiter.auth.dto.AdminBootstrapResponse;
import com.ratelimiter.auth.dto.AdminCreateUserRequest;
import com.ratelimiter.auth.dto.AdminUserResponse;
import com.ratelimiter.auth.dto.CreateTenantRequest;
import com.ratelimiter.auth.dto.MembershipResponse;
import com.ratelimiter.auth.dto.TenantResponse;
import com.ratelimiter.auth.service.AdminProvisioningService;
import com.ratelimiter.auth.service.MembershipRole;
import java.time.Instant;
import java.util.UUID;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.webmvc.test.autoconfigure.WebMvcTest;
import org.springframework.context.annotation.Import;
import org.springframework.http.MediaType;
import org.springframework.security.test.context.support.WithMockUser;
import org.springframework.security.oauth2.jwt.JwtDecoder;
import org.springframework.test.context.bean.override.mockito.MockitoBean;
import org.springframework.test.web.servlet.MockMvc;

@WebMvcTest(AdminProvisioningController.class)
@Import(SecurityConfig.class)
class AdminProvisioningControllerTests {

    @Autowired
    private MockMvc mockMvc;

    @MockitoBean
    private AdminProvisioningService provisioningService;

    @MockitoBean
    private JwtDecoder jwtDecoder;

    @Test
    void tenantCreationRequiresAuthentication() throws Exception {
        mockMvc.perform(post("/api/v1/auth/admin/tenants")
                .contentType(MediaType.APPLICATION_JSON)
                .content("""
                    {"tenantKey":"demo","name":"Demo"}
                    """))
            .andExpect(status().isUnauthorized());
    }

    @Test
    @WithMockUser(roles = "TENANT_ADMIN")
    void tenantCreationRequiresSuperAdminRole() throws Exception {
        mockMvc.perform(post("/api/v1/auth/admin/tenants")
                .contentType(MediaType.APPLICATION_JSON)
                .content("""
                    {"tenantKey":"demo","name":"Demo"}
                    """))
            .andExpect(status().isForbidden());
    }

    @Test
    @WithMockUser(roles = "SUPER_ADMIN")
    void superAdminCanCreateTenant() throws Exception {
        UUID tenantId = UUID.randomUUID();
        when(provisioningService.createTenant(any(CreateTenantRequest.class)))
            .thenReturn(new TenantResponse(
                tenantId,
                "demo",
                "Demo",
                Instant.parse("2026-01-01T00:00:00Z")
            ));

        mockMvc.perform(post("/api/v1/auth/admin/tenants")
                .contentType(MediaType.APPLICATION_JSON)
                .content("""
                    {"tenantKey":"demo","name":"Demo"}
                    """))
            .andExpect(status().isCreated());
    }

    @Test
    void userCreationRequiresAuthentication() throws Exception {
        mockMvc.perform(post(
                    "/api/v1/auth/admin/tenants/{tenantId}/users",
                    UUID.randomUUID()
                )
                .contentType(MediaType.APPLICATION_JSON)
                .content("""
                    {
                      "email":"new-user@example.com",
                      "password":"Valid-demo-password-123!",
                      "role":"TENANT_MEMBER"
                    }
                    """))
            .andExpect(status().isUnauthorized());
    }

    @Test
    @WithMockUser(roles = "TENANT_ADMIN")
    void userCreationRequiresSuperAdminRole() throws Exception {
        mockMvc.perform(post(
                    "/api/v1/auth/admin/tenants/{tenantId}/users",
                    UUID.randomUUID()
                )
                .contentType(MediaType.APPLICATION_JSON)
                .content("""
                    {
                      "email":"new-user@example.com",
                      "password":"Valid-demo-password-123!",
                      "role":"TENANT_MEMBER"
                    }
                    """))
            .andExpect(status().isForbidden());
    }

    @Test
    @WithMockUser(roles = "SUPER_ADMIN")
    void superAdminCanCreateUserInTenant() throws Exception {
        UUID userId = UUID.randomUUID();
        UUID tenantId = UUID.randomUUID();
        when(provisioningService.createUser(
                eq(tenantId),
                any(AdminCreateUserRequest.class)
        )).thenReturn(new AdminUserResponse(
            userId,
            "new-user@example.com",
            tenantId,
            MembershipRole.TENANT_MEMBER
        ));

        mockMvc.perform(post(
                    "/api/v1/auth/admin/tenants/{tenantId}/users",
                    tenantId
                )
                .contentType(MediaType.APPLICATION_JSON)
                .content("""
                    {
                      "email":"new-user@example.com",
                      "password":"Valid-demo-password-123!",
                      "role":"TENANT_MEMBER"
                    }
                    """))
            .andExpect(status().isCreated());

        verify(provisioningService).createUser(
            eq(tenantId),
            any(AdminCreateUserRequest.class)
        );
    }

    @Test
    void bootstrapEndpointAcceptsOneTimeTokenWithoutUserSession()
            throws Exception {
        when(provisioningService.bootstrap(
                eq("bootstrap-token"),
                any()
        )).thenReturn(new AdminBootstrapResponse(
            new TenantResponse(
                UUID.randomUUID(),
                "first-tenant",
                "First Tenant",
                Instant.parse("2026-01-01T00:00:00Z")
            ),
            new MembershipResponse(
                UUID.randomUUID(),
                UUID.randomUUID(),
                UUID.randomUUID(),
                MembershipRole.SUPER_ADMIN
            )
        ));

        mockMvc.perform(post("/api/v1/auth/admin/bootstrap")
                .header("X-Admin-Bootstrap-Token", "bootstrap-token")
                .contentType(MediaType.APPLICATION_JSON)
                .content("""
                    {
                      "email":"admin@example.com",
                      "initialPassword":"Valid-demo-password-123!",
                      "tenantKey":"first-tenant",
                      "tenantName":"First Tenant"
                    }
                    """))
            .andExpect(status().isCreated());

        verify(provisioningService).bootstrap(
            eq("bootstrap-token"),
            any()
        );
    }
}
