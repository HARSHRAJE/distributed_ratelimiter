
package com.ratelimiter.policy.dto.request;

import jakarta.validation.constraints.*;
import java.math.BigDecimal;

public record CreateServiceRequest(

    @NotBlank
    @Size(max = 100)
    String serviceKey,

    @NotNull
    @Positive
    Integer globalCapacity,

    @NotNull
    @DecimalMin("0.001")
    BigDecimal globalRefillRate,

    @NotNull
    @DecimalMin("0.001")
    BigDecimal hardMaxRefillRate

) {}
