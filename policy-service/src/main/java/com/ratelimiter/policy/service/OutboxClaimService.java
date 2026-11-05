package com.ratelimiter.policy.service;

import com.ratelimiter.policy.repository.OutboxClaimRepository;
import java.time.Instant;
import java.util.List;
import java.util.UUID;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
public class OutboxClaimService {

    private final OutboxClaimRepository claimRepository;

    public OutboxClaimService(OutboxClaimRepository claimRepository) {
        this.claimRepository = claimRepository;
    }

    @Transactional
    public List<UUID> claimBatch(int batchSize) {
        if (batchSize <= 0) {
            throw new IllegalArgumentException(
                "Batch size must be greater than zero"
            );
        }

        Instant now = Instant.now();
        return claimRepository.claimBatch(
            now,
            now.plusSeconds(120),
            batchSize
        );
    }
}
