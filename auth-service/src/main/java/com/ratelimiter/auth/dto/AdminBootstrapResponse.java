package com.ratelimiter.auth.dto;

public record AdminBootstrapResponse(
    TenantResponse tenant,
    MembershipResponse membership
) {}
