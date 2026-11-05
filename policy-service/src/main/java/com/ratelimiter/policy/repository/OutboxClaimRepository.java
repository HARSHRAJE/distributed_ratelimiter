package com.ratelimiter.policy.repository;

import java.sql.Timestamp;
import java.time.Instant;
import java.util.List;
import java.util.UUID;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;

@Repository
public class OutboxClaimRepository {

    private static final String CLAIM_BATCH_SQL = """
        WITH candidates AS (
            SELECT id
            FROM policy_outbox_events
            WHERE (
                status = 'PENDING'
                OR (
                    status = 'PROCESSING'
                    AND locked_until <= ?
                )
            )
            AND available_at <= ?
            ORDER BY created_at, id
            LIMIT ?
            FOR UPDATE SKIP LOCKED
        )
        UPDATE policy_outbox_events AS event
        SET status = 'PROCESSING',
            locked_until = ?,
            attempts = attempts + 1
        FROM candidates
        WHERE event.id = candidates.id
        RETURNING event.id
        """;

    private final JdbcTemplate jdbcTemplate;

    public OutboxClaimRepository(JdbcTemplate jdbcTemplate) {
        this.jdbcTemplate = jdbcTemplate;
    }

    public List<UUID> claimBatch(
            Instant now,
            Instant lockedUntil,
            int batchSize) {

        return jdbcTemplate.query(
            CLAIM_BATCH_SQL,
            (resultSet, rowNumber) ->
                resultSet.getObject("id", UUID.class),
            Timestamp.from(now),
            Timestamp.from(now),
            batchSize,
            Timestamp.from(lockedUntil)
        );
    }
}
