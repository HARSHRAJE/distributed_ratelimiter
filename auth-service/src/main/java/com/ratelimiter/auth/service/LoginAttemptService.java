package com.ratelimiter.auth.service;

import java.sql.Timestamp;
import java.time.Instant;
import java.util.UUID;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;

@Service
public class LoginAttemptService {

    private final JdbcTemplate jdbcTemplate;

    public LoginAttemptService(JdbcTemplate jdbcTemplate) {
        this.jdbcTemplate = jdbcTemplate;
    }

    public AttemptState lock(String email) {
        jdbcTemplate.update(
            """
            INSERT INTO login_attempts(email, failed_attempts)
            VALUES (?, 0)
            ON CONFLICT (email) DO NOTHING
            """,
            email
        );

        return jdbcTemplate.queryForObject(
            """
            SELECT failed_attempts, locked_until
            FROM login_attempts
            WHERE email = ?
            FOR UPDATE
            """,
            (resultSet, rowNumber) -> {
                Timestamp lockedUntil =
                    resultSet.getTimestamp("locked_until");
                return new AttemptState(
                    resultSet.getInt("failed_attempts"),
                    lockedUntil == null ? null : lockedUntil.toInstant()
                );
            },
            email
        );
    }

    public void recordFailure(
            String email,
            AttemptState previous,
            int maximumAttempts,
            Instant now,
            Instant lockDurationEnd) {

        int nextAttempt = previous.lockedUntil() != null
            && !previous.lockedUntil().isAfter(now)
            ? 1
            : previous.failedAttempts() + 1;
        Instant lockedUntil = nextAttempt >= maximumAttempts
            ? lockDurationEnd
            : null;

        jdbcTemplate.update(
            """
            UPDATE login_attempts
            SET failed_attempts = ?,
                locked_until = ?,
                updated_at = ?
            WHERE email = ?
            """,
            nextAttempt,
            lockedUntil == null ? null : Timestamp.from(lockedUntil),
            Timestamp.from(now),
            email
        );
    }

    public void clear(String email) {
        jdbcTemplate.update(
            """
            UPDATE login_attempts
            SET failed_attempts = 0,
                locked_until = NULL,
                updated_at = ?
            WHERE email = ?
            """,
            Timestamp.from(Instant.now()),
            email
        );
    }

    public record AttemptState(int failedAttempts, Instant lockedUntil) {}
}
