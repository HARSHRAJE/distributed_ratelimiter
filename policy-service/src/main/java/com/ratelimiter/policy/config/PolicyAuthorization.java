package com.ratelimiter.policy.config;

import com.ratelimiter.policy.dto.response.PolicyResponse;
import java.util.List;
import org.springframework.security.access.AccessDeniedException;
import org.springframework.security.oauth2.jwt.Jwt;

public final class PolicyAuthorization {

    private PolicyAuthorization() {}

    public static void requireServiceAccess(Jwt jwt, String serviceKey) {
        List<String> roles = jwt.getClaimAsStringList("roles");
        if (roles != null && roles.contains("SUPER_ADMIN")) {
            return;
        }
        List<String> services = jwt.getClaimAsStringList("service_keys");
        if (roles == null
                || !roles.contains("SERVICE_ADMIN")
                || services == null
                || !services.contains(serviceKey)) {
            throw new AccessDeniedException("Service access is not authorized");
        }
    }

    public static void requireTenantOrServiceRead(
            Jwt jwt,
            String serviceKey,
            String tenantId) {
        List<String> roles = jwt.getClaimAsStringList("roles");
        if (roles != null && roles.contains("SUPER_ADMIN")) {
            return;
        }
        if (roles != null && roles.contains("SERVICE_ADMIN")) {
            requireServiceAccess(jwt, serviceKey);
            return;
        }
        if (roles != null
                && roles.contains("TENANT_ADMIN")
                && tenantId.equals(jwt.getClaimAsString("tenant_id"))) {
            return;
        }
        throw new AccessDeniedException("Tenant policy access is not authorized");
    }

    public static void requirePolicyRead(
            Jwt jwt,
            PolicyResponse policy) {
        requireTenantOrServiceRead(
            jwt,
            policy.serviceKey(),
            policy.tenantId()
        );
    }

    public static String actorId(Jwt jwt) {
        return jwt.getSubject();
    }
}
