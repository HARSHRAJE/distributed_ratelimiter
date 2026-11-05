package com.ratelimiter.policy.service;

import com.ratelimiter.policy.entity.OutboxEventEntity;
import com.ratelimiter.policy.entity.OutboxStatus;
import com.ratelimiter.policy.repository.OutboxEventRepository;
import java.time.Instant;
import java.time.Duration;
import java.util.UUID;
import io.micrometer.core.instrument.Counter;
import io.micrometer.core.instrument.Gauge;
import io.micrometer.core.instrument.MeterRegistry;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
public class OutboxStatusService {

    private static final Logger log =
        LoggerFactory.getLogger(OutboxStatusService.class);

    private final OutboxEventRepository repository;
    private final Counter exhaustedEvents;

    public OutboxStatusService(
            OutboxEventRepository repository,
            MeterRegistry meterRegistry) {
        this.repository = repository;
        this.exhaustedEvents = Counter.builder("policy.outbox.exhausted")
            .description("Outbox events that exhausted their retry limit")
            .register(meterRegistry);
        Gauge.builder(
            "policy.outbox.pending",
            repository,
            outbox -> outbox.countByStatus(OutboxStatus.PENDING)
        ).description(
            "Number of pending policy outbox events"
        ).register(meterRegistry);
        Gauge.builder(
            "policy.outbox.processing",
            repository,
            outbox -> outbox.countByStatus(OutboxStatus.PROCESSING)
        ).description(
            "Number of policy outbox events being processed"
        ).register(meterRegistry);
        Gauge.builder(
            "policy.outbox.failed",
            repository,
            outbox -> outbox.countByStatus(OutboxStatus.FAILED)
        ).description(
            "Number of policy outbox events that exhausted retries"
        ).register(meterRegistry);
        Gauge.builder(
            "policy.outbox.sync.lag",
            repository,
            OutboxStatusService::oldestPendingAgeSeconds
        ).description(
            "Age in seconds of the oldest pending policy outbox event"
        ).register(meterRegistry);
    }

    private static double oldestPendingAgeSeconds(
            OutboxEventRepository repository) {
        return repository.findFirstByStatusOrderByCreatedAtAsc(
                OutboxStatus.PENDING
            )
            .map(event -> Duration.between(
                event.getCreatedAt(),
                Instant.now()
            ).toNanos() / 1_000_000_000.0)
            .orElse(0.0);
    }

    @Transactional
    public void markPublished(UUID eventId) {
        OutboxEventEntity event = repository.findById(eventId)
            .orElseThrow(() -> new IllegalStateException(
                "Outbox event not found: " + eventId
            ));

        event.setStatus(OutboxStatus.PUBLISHED);
        event.setPublishedAt(Instant.now());
        event.setLockedUntil(null);
        event.setLastError(null);
    }

    @Transactional
    public void markFailed(UUID eventId, String error) {
        OutboxEventEntity event = repository.findById(eventId)
            .orElseThrow(() -> new IllegalStateException(
                "Outbox event not found: " + eventId
            ));

        event.setLastError(error);
        event.setLockedUntil(null);

        if (event.getAttempts() >= 10) {
            event.setStatus(OutboxStatus.FAILED);
            log.error(
                "Outbox event exhausted retries and requires operational attention: {}",
                eventId
            );
            exhaustedEvents.increment();
            return;
        }

        event.setStatus(OutboxStatus.PENDING);

        long delaySeconds = Math.min(
            300,
            1L << Math.min(event.getAttempts(), 9)
        );

        event.setAvailableAt(
            Instant.now().plusSeconds(delaySeconds)
        );
    }
}
