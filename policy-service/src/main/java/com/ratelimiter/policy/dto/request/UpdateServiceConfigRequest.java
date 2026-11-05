package com.ratelimiter.policy.dto.request;

import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Positive;
import jakarta.validation.constraints.DecimalMin;
import java.math.BigDecimal;

public record UpdateServiceConfigRequest(
    @NotNull @Positive Integer globalCapacity,
    @NotNull @DecimalMin("0.001") BigDecimal globalRefillRate
) {}
