package com.ratelimiter.policy.repository;

import com.ratelimiter.policy.entity.OutboxEventEntity;
import com.ratelimiter.policy.entity.OutboxStatus;
import java.util.Optional;
import java.util.UUID;
import org.springframework.data.jpa.repository.JpaRepository;

public interface OutboxEventRepository
        extends JpaRepository<OutboxEventEntity, UUID> {

    long countByStatus(OutboxStatus status);

    Optional<OutboxEventEntity> findFirstByStatusOrderByCreatedAtAsc(
        OutboxStatus status
    );
}
