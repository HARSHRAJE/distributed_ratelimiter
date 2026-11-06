CREATE TABLE chaos_experiments (
    id UUID PRIMARY KEY,
    experiment_code VARCHAR(50) NOT NULL CHECK (
        experiment_code IN (
            'CH-01', 'CH-02', 'CH-03', 'CH-04', 'CH-05',
            'CH-06', 'CH-07', 'CH-08', 'CH-09', 'CH-10'
        )
    ),
    scenario VARCHAR(100) NOT NULL,
    target_component VARCHAR(100) NOT NULL,
    service_key VARCHAR(100) NOT NULL,
    test_environment_id VARCHAR(100) NOT NULL,
    status VARCHAR(30) NOT NULL CHECK (
        status IN ('QUEUED', 'RUNNING', 'COMPLETED', 'FAILED')
    ),
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    fault_duration_seconds INTEGER NOT NULL
        CHECK (fault_duration_seconds BETWEEN 1 AND 30),
    operator_note TEXT NOT NULL DEFAULT '',
    error TEXT,
    CONSTRAINT ck_chaos_experiment_times CHECK (
        completed_at IS NULL
        OR started_at IS NULL
        OR completed_at >= started_at
    )
);

CREATE INDEX idx_chaos_experiments_status_created
    ON chaos_experiments(status, created_at);
CREATE INDEX idx_chaos_experiments_env_service_created
    ON chaos_experiments(
        test_environment_id,
        service_key,
        created_at DESC
    );

CREATE TABLE chaos_experiment_results (
    id UUID PRIMARY KEY,
    experiment_id UUID NOT NULL
        REFERENCES chaos_experiments(id),
    requests_sent BIGINT NOT NULL DEFAULT 0 CHECK (requests_sent >= 0),
    accepted_requests BIGINT NOT NULL DEFAULT 0
        CHECK (accepted_requests >= 0),
    rejected_requests BIGINT NOT NULL DEFAULT 0
        CHECK (rejected_requests >= 0),
    backend_errors BIGINT NOT NULL DEFAULT 0 CHECK (backend_errors >= 0),
    gateway_errors BIGINT NOT NULL DEFAULT 0 CHECK (gateway_errors >= 0),
    policy_consistency BOOLEAN NOT NULL,
    recovery_success BOOLEAN NOT NULL,
    recovery_time_ms BIGINT CHECK (
        recovery_time_ms IS NULL OR recovery_time_ms >= 0
    ),
    safety_violations BIGINT NOT NULL DEFAULT 0
        CHECK (safety_violations >= 0),
    details JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_chaos_experiment_result_experiment UNIQUE (experiment_id)
);

CREATE INDEX idx_chaos_experiment_results_created
    ON chaos_experiment_results(created_at DESC);
