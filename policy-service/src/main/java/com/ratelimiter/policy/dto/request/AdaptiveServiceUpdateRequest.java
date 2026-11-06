package com.ratelimiter.policy.dto.request;

import jakarta.validation.constraints.DecimalMin;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Positive;
import java.math.BigDecimal;
import java.util.UUID;

public record AdaptiveServiceUpdateRequest(
    @NotNull @Positive Long expectedConfigVersion,
    @NotNull @Positive Integer globalCapacity,
    @NotNull @DecimalMin("0.001") BigDecimal globalRefillRate,
    @NotNull UUID executionId
) {}
