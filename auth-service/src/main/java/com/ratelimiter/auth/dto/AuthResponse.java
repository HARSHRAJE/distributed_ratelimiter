package com.ratelimiter.auth.dto;

import java.util.List;
import java.util.UUID;

public record AuthResponse(
    String accessToken,
    String tokenType,
    long expiresIn,
    UUID userId,
    UUID tenantId,
    String tenantKey,
    List<String> roles
) {}
