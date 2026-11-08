package com.ratelimiter.auth.dto;

import com.ratelimiter.auth.service.MembershipRole;
import jakarta.validation.constraints.Email;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Size;

public record AdminCreateUserRequest(
    @NotBlank @Email @Size(max = 255) String email,
    @NotBlank @Size(min = 12, max = 72) String password,
    @NotNull MembershipRole role
) {}
