package com.ratelimiter.auth.dto;

import com.ratelimiter.auth.service.MembershipRole;
import jakarta.validation.constraints.NotNull;
import java.util.UUID;

public record CreateMembershipRequest(
    @NotNull UUID userId,
    @NotNull MembershipRole role
) {}
