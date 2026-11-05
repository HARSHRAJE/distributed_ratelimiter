package com.ratelimiter.policy.event;

import java.util.UUID;

public record ServiceConfigReconcileEvent(UUID serviceId) {}
