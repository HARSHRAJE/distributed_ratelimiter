package com.ratelimiter.policy.service;

import com.ratelimiter.policy.entity.OutboxEventEntity;
import com.ratelimiter.policy.redis.ActivePolicySnapshotBuilder;
import com.ratelimiter.policy.redis.RedisPolicyWriter;
import com.ratelimiter.policy.redis.RedisServiceConfigWriter;
import com.ratelimiter.policy.redis.ServiceConfigSnapshotBuilder;
import org.springframework.stereotype.Component;

@Component
public class RedisPolicyEventProcessor implements PolicyEventProcessor {

    private final ActivePolicySnapshotBuilder policySnapshotBuilder;
    private final RedisPolicyWriter redisPolicyWriter;
    private final ServiceConfigSnapshotBuilder serviceSnapshotBuilder;
    private final RedisServiceConfigWriter redisServiceConfigWriter;

    public RedisPolicyEventProcessor(
            ActivePolicySnapshotBuilder policySnapshotBuilder,
            RedisPolicyWriter redisPolicyWriter,
            ServiceConfigSnapshotBuilder serviceSnapshotBuilder,
            RedisServiceConfigWriter redisServiceConfigWriter) {
        this.policySnapshotBuilder = policySnapshotBuilder;
        this.redisPolicyWriter = redisPolicyWriter;
        this.serviceSnapshotBuilder = serviceSnapshotBuilder;
        this.redisServiceConfigWriter = redisServiceConfigWriter;
    }

    @Override
    public void process(OutboxEventEntity event) {
        switch (event.getEventType()) {
            case "POLICY_RECONCILE" -> redisPolicyWriter.write(
                policySnapshotBuilder.build(event.getAggregateId())
            );
            case "SERVICE_CONFIG_RECONCILE" -> redisServiceConfigWriter.write(
                serviceSnapshotBuilder.build(event.getAggregateId())
            );
            default -> throw new IllegalArgumentException(
                "Unsupported event type: " + event.getEventType()
            );
        }
    }
}
