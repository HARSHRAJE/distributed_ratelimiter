package com.ratelimiter.auth.dto;

import java.util.List;
import java.util.UUID;

public record UserMeResponse(
    UUID userId,
    String email,
    UUID tenantId,
    String tenantKey,
    List<String> roles
) {}
