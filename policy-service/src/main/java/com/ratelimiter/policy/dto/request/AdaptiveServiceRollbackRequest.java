package com.ratelimiter.policy.dto.request;

import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Positive;
import java.util.UUID;

public record AdaptiveServiceRollbackRequest(
    @NotNull @Positive Long expectedActiveVersion,
    @NotNull @Positive Long restoredFromVersion,
    @NotNull UUID rollbackId
) {}
