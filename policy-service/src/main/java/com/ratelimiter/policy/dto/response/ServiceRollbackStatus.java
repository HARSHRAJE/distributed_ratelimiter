package com.ratelimiter.policy.dto.response;

import java.math.BigDecimal;
import java.util.UUID;

public record ServiceRollbackStatus(
    UUID rollbackId,
    UUID serviceId,
    Long failedVersion,
    Long restoredFromVersion,
    Long rollbackVersion,
    Integer globalCapacity,
    BigDecimal globalRefillRate,
    Boolean adaptiveEnabled
) {}
