CREATE TABLE policy_executions (
    id UUID PRIMARY KEY,
    recommendation_id UUID NOT NULL
        REFERENCES policy_recommendations(id),
    service_key VARCHAR(100) NOT NULL,
    policy_id UUID,
    previous_version BIGINT NOT NULL CHECK (previous_version > 0),
    resulting_version BIGINT,
    effective_config_verified_at TIMESTAMPTZ,
    previous_rate NUMERIC(14, 3) NOT NULL CHECK (previous_rate > 0),
    proposed_rate NUMERIC(14, 3) NOT NULL CHECK (proposed_rate > 0),
    status VARCHAR(24) NOT NULL CHECK (
        status IN (
            'PENDING', 'VALIDATING', 'SUBMITTED', 'APPLIED',
            'FAILED', 'ROLLBACK_PENDING', 'ROLLED_BACK'
        )
    ),
    failure_reason TEXT,
    started_at TIMESTAMPTZ NOT NULL,
    completed_at TIMESTAMPTZ
);

CREATE INDEX idx_policy_executions_service_started
    ON policy_executions(service_key, started_at DESC);

CREATE INDEX idx_policy_executions_recommendation
    ON policy_executions(recommendation_id, started_at DESC);

CREATE UNIQUE INDEX uq_policy_executions_active_service
    ON policy_executions(service_key)
    WHERE status IN (
        'PENDING', 'VALIDATING', 'SUBMITTED', 'ROLLBACK_PENDING'
    );

CREATE TABLE execution_service_controls (
    service_key VARCHAR(100) PRIMARY KEY,
    enabled BOOLEAN NOT NULL DEFAULT FALSE,
    manual_override BOOLEAN NOT NULL DEFAULT FALSE,
    rollout_started_at TIMESTAMPTZ,
    paused_reason TEXT,
    updated_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE execution_global_controls (
    id VARCHAR(20) PRIMARY KEY CHECK (id = 'global'),
    kill_switch_active BOOLEAN NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL
);
