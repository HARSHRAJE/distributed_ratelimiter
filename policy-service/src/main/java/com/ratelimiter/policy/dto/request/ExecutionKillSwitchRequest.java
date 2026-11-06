package com.ratelimiter.policy.dto.request;

import jakarta.validation.constraints.NotNull;

public record ExecutionKillSwitchRequest(
    @NotNull Boolean active
) {}
