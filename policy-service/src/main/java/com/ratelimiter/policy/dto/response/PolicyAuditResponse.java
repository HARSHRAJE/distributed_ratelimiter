package com.ratelimiter.policy.dto.response;

import java.time.Instant;
import java.util.UUID;

public record PolicyAuditResponse(
    UUID id,
    UUID policyId,
    String action,
    Long previousVersion,
    Long newVersion,
    String actor,
    String reason,
    Instant occurredAt
) {}
