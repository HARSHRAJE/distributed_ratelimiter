CREATE TABLE policy_rollback_events (
    id UUID PRIMARY KEY,
    execution_id UUID NOT NULL UNIQUE
        REFERENCES policy_executions(id),
    service_key VARCHAR(100) NOT NULL,
    failed_version BIGINT NOT NULL CHECK (failed_version > 0),
    restored_from_version BIGINT NOT NULL CHECK (restored_from_version > 0),
    rollback_version BIGINT CHECK (rollback_version > failed_version),
    trigger_metric VARCHAR(50) NOT NULL,
    trigger_value NUMERIC(14, 3) NOT NULL,
    threshold_value NUMERIC(14, 3) NOT NULL,
    reason TEXT NOT NULL,
    status VARCHAR(24) NOT NULL CHECK (
        status IN (
            'DETECTED', 'INITIATED', 'POLICY_RESTORED', 'REDIS_SYNCED',
            'COMPLETED', 'FAILED'
        )
    ),
    created_at TIMESTAMPTZ NOT NULL,
    completed_at TIMESTAMPTZ,
    effective_config_verified_at TIMESTAMPTZ
);

CREATE INDEX idx_policy_rollback_events_service_created
    ON policy_rollback_events(service_key, created_at DESC);
