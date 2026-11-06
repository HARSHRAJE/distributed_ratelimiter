package com.ratelimiter.policy.dto.request;

import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Positive;

public record AdaptiveControlRequest(
    @NotNull @Positive Long expectedConfigVersion,
    @NotNull Boolean enabled
) {}
