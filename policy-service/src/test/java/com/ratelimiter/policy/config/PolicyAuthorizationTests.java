package com.ratelimiter.policy.config;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import java.time.Instant;
import java.util.List;
import org.junit.jupiter.api.Test;
import org.springframework.security.access.AccessDeniedException;
import org.springframework.security.oauth2.jwt.Jwt;

class PolicyAuthorizationTests {

    private static final String TENANT_A =
        "0795a60c-05af-4ad3-b220-7cc572362aa1";
    private static final String TENANT_B =
        "e5f7c071-0106-43d1-bde3-16ae85f62b03";

    @Test
    void tenantAdministratorCanReadOnlyOwnTenant() {
        Jwt tenant = jwt(
            TENANT_A,
            List.of("TENANT_ADMIN"),
            null
        );

        PolicyAuthorization.requireTenantOrServiceRead(
            tenant,
            "orders-service",
            TENANT_A
        );
        assertThatThrownBy(() ->
            PolicyAuthorization.requireTenantOrServiceRead(
                tenant,
                "orders-service",
                TENANT_B
            )
        ).isInstanceOf(AccessDeniedException.class);
    }

    @Test
    void serviceAdministratorMustHaveExplicitServiceMembership() {
        Jwt serviceAdmin = jwt(
            TENANT_A,
            List.of("SERVICE_ADMIN"),
            List.of("orders-service")
        );

        PolicyAuthorization.requireServiceAccess(
            serviceAdmin,
            "orders-service"
        );
        assertThatThrownBy(() ->
            PolicyAuthorization.requireServiceAccess(
                serviceAdmin,
                "billing-service"
            )
        ).isInstanceOf(AccessDeniedException.class);
    }

    @Test
    void superAdministratorCanAccessServicesWithoutServiceClaims() {
        PolicyAuthorization.requireServiceAccess(
            jwt(TENANT_A, List.of("SUPER_ADMIN"), null),
            "orders-service"
        );
    }

    private static Jwt jwt(
            String tenantId,
            List<String> roles,
            List<String> serviceKeys) {
        Jwt.Builder builder = Jwt.withTokenValue("non-secret-test-value")
            .header("alg", "RS256")
            .subject(TENANT_A)
            .issuedAt(Instant.now())
            .expiresAt(Instant.now().plusSeconds(60))
            .claim("tenant_id", tenantId)
            .claim("roles", roles);
        if (serviceKeys != null) {
            builder.claim("service_keys", serviceKeys);
        }
        return builder.build();
    }
}
