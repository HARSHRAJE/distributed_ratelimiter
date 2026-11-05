package com.ratelimiter.policy.event;

import java.util.UUID;

public record PolicyReconcileEvent(
    UUID policyId,
    String action
) {}
