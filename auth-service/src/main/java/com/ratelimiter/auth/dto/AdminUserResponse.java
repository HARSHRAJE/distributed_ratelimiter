package com.ratelimiter.auth.dto;

import com.ratelimiter.auth.service.MembershipRole;
import java.util.UUID;

public record AdminUserResponse(
    UUID userId,
    String email,
    UUID tenantId,
    MembershipRole role
) {}
