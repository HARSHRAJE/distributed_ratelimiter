package com.ratelimiter.policy.dto.request;

import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Positive;
import jakarta.validation.constraints.Size;

public record RollbackPolicyRequest(

    @NotNull
    @Positive
    Long expectedActiveVersion,

    @NotBlank
    @Size(max = 128)
    String createdBy

) {}
