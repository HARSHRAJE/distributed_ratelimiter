package com.ratelimiter.policy.service;

import com.ratelimiter.policy.entity.OutboxEventEntity;

public interface PolicyEventProcessor {

    void process(OutboxEventEntity event);
}
