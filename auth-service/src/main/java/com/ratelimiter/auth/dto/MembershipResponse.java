package com.ratelimiter.auth.dto;

import com.ratelimiter.auth.service.MembershipRole;
import java.util.UUID;

public record MembershipResponse(
    UUID membershipId,
    UUID userId,
    UUID tenantId,
    MembershipRole role
) {}
