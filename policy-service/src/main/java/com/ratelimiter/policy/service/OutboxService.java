package com.ratelimiter.policy.service;

import com.ratelimiter.policy.entity.OutboxEventEntity;
import com.ratelimiter.policy.event.PolicyReconcileEvent;
import com.ratelimiter.policy.event.ServiceConfigReconcileEvent;
import com.ratelimiter.policy.repository.OutboxEventRepository;
import java.time.Instant;
import java.util.UUID;
import org.springframework.stereotype.Service;
import tools.jackson.core.JacksonException;
import tools.jackson.databind.ObjectMapper;

@Service
public class OutboxService {

    private final OutboxEventRepository repository;
    private final ObjectMapper objectMapper;

    public OutboxService(
            OutboxEventRepository repository,
            ObjectMapper objectMapper) {

        this.repository = repository;
        this.objectMapper = objectMapper;
    }

    public void publishPolicyReconciliation(
            UUID policyId,
            String action) {

        try {
            PolicyReconcileEvent event =
                new PolicyReconcileEvent(policyId, action);

            OutboxEventEntity outbox = new OutboxEventEntity();
            outbox.setEventType("POLICY_RECONCILE");
            outbox.setAggregateType("RATE_LIMIT_POLICY");
            outbox.setAggregateId(policyId);
            outbox.setPayload(objectMapper.writeValueAsString(event));
            outbox.setAvailableAt(Instant.now());

            repository.save(outbox);
        } catch (JacksonException ex) {
            throw new IllegalStateException(
                "Could not serialize policy reconciliation event",
                ex
            );
        }
    }

    public void publishServiceConfigReconciliation(UUID serviceId) {
        try {
            ServiceConfigReconcileEvent event =
                new ServiceConfigReconcileEvent(serviceId);

            OutboxEventEntity outbox = new OutboxEventEntity();
            outbox.setEventType("SERVICE_CONFIG_RECONCILE");
            outbox.setAggregateType("SERVICE");
            outbox.setAggregateId(serviceId);
            outbox.setPayload(objectMapper.writeValueAsString(event));
            outbox.setAvailableAt(Instant.now());

            repository.save(outbox);
        } catch (JacksonException ex) {
            throw new IllegalStateException(
                "Could not serialize service configuration reconciliation event",
                ex
            );
        }
    }
}
