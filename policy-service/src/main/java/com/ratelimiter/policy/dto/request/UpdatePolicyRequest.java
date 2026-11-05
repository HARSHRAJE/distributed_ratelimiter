package com.ratelimiter.policy.dto.request;

import jakarta.validation.constraints.DecimalMin;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Positive;
import jakarta.validation.constraints.Size;
import java.math.BigDecimal;

public record UpdatePolicyRequest(

    @NotNull
    @Positive
    Long expectedActiveVersion,

    @NotNull
    @Positive
    Integer tenantCapacity,

    @NotNull
    @DecimalMin("0.001")
    BigDecimal tenantRefillRate,

    @NotNull
    @Positive
    Integer routeCapacity,

    @NotNull
    @DecimalMin("0.001")
    BigDecimal routeRefillRate,

    @NotNull
    @DecimalMin("0.001")
    BigDecimal minRefillRate,

    @NotNull
    @DecimalMin("0.001")
    BigDecimal maxRefillRate,

    @NotBlank
    @Size(max = 128)
    String createdBy

) {}
