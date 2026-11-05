package com.ratelimiter.policy.dto.request;

import jakarta.validation.constraints.*;
import java.math.BigDecimal;

public record CreatePolicyRequest(

    @NotBlank
    @Size(max = 100)
    String serviceKey,

    @NotBlank
    @Size(max = 128)
    String tenantId,

    @NotBlank
    @Size(max = 128)
    String routeId,

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