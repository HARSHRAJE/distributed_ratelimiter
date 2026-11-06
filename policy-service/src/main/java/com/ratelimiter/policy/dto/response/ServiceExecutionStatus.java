package com.ratelimiter.policy.dto.response;

import java.math.BigDecimal;
import java.util.UUID;

public record ServiceExecutionStatus(
    UUID executionId,
    boolean accepted,
    Long resultingVersion,
    BigDecimal resultingRate
) {}
