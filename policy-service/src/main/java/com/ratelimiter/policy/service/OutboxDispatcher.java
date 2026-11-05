package com.ratelimiter.policy.service;

import com.ratelimiter.policy.entity.OutboxEventEntity;
import com.ratelimiter.policy.repository.OutboxEventRepository;
import java.util.List;
import java.util.UUID;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

@Component
@ConditionalOnProperty(
    name = "policy.outbox.dispatcher.enabled",
    havingValue = "true"
)
public class OutboxDispatcher {

    private static final Logger log =
        LoggerFactory.getLogger(OutboxDispatcher.class);

    private final OutboxClaimService claimService;
    private final OutboxEventRepository repository;
    private final PolicyEventProcessor processor;
    private final OutboxStatusService statusService;

    public OutboxDispatcher(
            OutboxClaimService claimService,
            OutboxEventRepository repository,
            PolicyEventProcessor processor,
            OutboxStatusService statusService) {

        this.claimService = claimService;
        this.repository = repository;
        this.processor = processor;
        this.statusService = statusService;
    }

    @Scheduled(fixedDelay = 5000)
    public void dispatch() {
        List<UUID> claimedIds = claimService.claimBatch(20);

        for (UUID eventId : claimedIds) {
            try {
                OutboxEventEntity event = repository.findById(eventId)
                    .orElseThrow(() -> new IllegalStateException(
                        "Claimed outbox event not found: " + eventId
                    ));
                processor.process(event);
                statusService.markPublished(eventId);
            } catch (Exception ex) {
                log.error(
                    "Outbox event processing failed: {}",
                    eventId,
                    ex
                );
                statusService.markFailed(
                    eventId,
                    ex.getMessage()
                );
            }
        }
    }
}
