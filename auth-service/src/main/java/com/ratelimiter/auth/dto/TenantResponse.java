package com.ratelimiter.auth.dto;

import java.time.Instant;
import java.util.UUID;

public record TenantResponse(
    UUID tenantId,
    String tenantKey,
    String name,
    Instant createdAt
) {}
