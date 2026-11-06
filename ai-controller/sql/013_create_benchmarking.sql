CREATE TABLE benchmark_runs (
    id UUID PRIMARY KEY,
    batch_id UUID NOT NULL,
    execution_order INTEGER NOT NULL CHECK (execution_order BETWEEN 0 AND 2),
    strategy VARCHAR(32) NOT NULL CHECK (
        strategy IN ('STATIC', 'RULE_BASED', 'AI_SLA_ADAPTIVE')
    ),
    scenario VARCHAR(40) NOT NULL CHECK (
        scenario IN (
            'STEADY_TRAFFIC',
            'SUDDEN_SPIKE',
            'GRADUAL_RAMP',
            'BURST_TRAFFIC',
            'TENANT_HOTSPOT',
            'ROUTE_IMBALANCE',
            'BACKEND_DEGRADATION',
            'REDIS_FAILURE',
            'CONTROLLER_FAILURE',
            'POLICY_SYNC_DELAY'
        )
    ),
    service_key VARCHAR(100) NOT NULL,
    environment_id VARCHAR(100) NOT NULL,
    status VARCHAR(20) NOT NULL CHECK (
        status IN ('QUEUED', 'RUNNING', 'COMPLETED', 'FAILED')
    ),
    config_version VARCHAR(200) NOT NULL,
    git_commit VARCHAR(80) NOT NULL,
    k6_script_version VARCHAR(40) NOT NULL,
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    duration_seconds INTEGER NOT NULL CHECK (duration_seconds BETWEEN 10 AND 3600),
    warmup_seconds INTEGER NOT NULL CHECK (warmup_seconds BETWEEN 0 AND 600),
    tenant_count INTEGER NOT NULL CHECK (tenant_count BETWEEN 1 AND 10000),
    start_rps INTEGER NOT NULL CHECK (start_rps BETWEEN 1 AND 1000),
    peak_rps INTEGER NOT NULL CHECK (peak_rps BETWEEN start_rps AND 1000),
    fault_injection_confirmed BOOLEAN NOT NULL DEFAULT FALSE,
    slo_thresholds JSONB NOT NULL,
    workload_parameters JSONB NOT NULL,
    error TEXT,
    created_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT ck_benchmark_run_times
        CHECK (completed_at IS NULL OR started_at IS NULL OR completed_at >= started_at),
    CONSTRAINT uq_benchmark_run_batch_strategy UNIQUE (batch_id, strategy)
);

CREATE INDEX idx_benchmark_runs_service_scenario_created
    ON benchmark_runs(service_key, scenario, created_at DESC);
CREATE INDEX idx_benchmark_runs_batch
    ON benchmark_runs(batch_id);
CREATE INDEX idx_benchmark_runs_environment
    ON benchmark_runs(environment_id, service_key, scenario);
CREATE INDEX idx_benchmark_runs_status_created
    ON benchmark_runs(status, created_at);

CREATE TABLE benchmark_results (
    id UUID PRIMARY KEY,
    run_id UUID NOT NULL UNIQUE REFERENCES benchmark_runs(id),
    incoming_rps NUMERIC(14, 3) CHECK (incoming_rps IS NULL OR incoming_rps >= 0),
    accepted_rps NUMERIC(14, 3) CHECK (accepted_rps IS NULL OR accepted_rps >= 0),
    successful_rps NUMERIC(14, 3) CHECK (successful_rps IS NULL OR successful_rps >= 0),
    p50_latency_ms NUMERIC(14, 3) CHECK (p50_latency_ms IS NULL OR p50_latency_ms >= 0),
    p95_latency_ms NUMERIC(14, 3) CHECK (p95_latency_ms IS NULL OR p95_latency_ms >= 0),
    p99_latency_ms NUMERIC(14, 3) CHECK (p99_latency_ms IS NULL OR p99_latency_ms >= 0),
    backend_p95_latency_ms NUMERIC(14, 3)
        CHECK (backend_p95_latency_ms IS NULL OR backend_p95_latency_ms >= 0),
    rejection_ratio NUMERIC(10, 6)
        CHECK (rejection_ratio IS NULL OR rejection_ratio BETWEEN 0 AND 1),
    backend_error_ratio NUMERIC(10, 6)
        CHECK (backend_error_ratio IS NULL OR backend_error_ratio BETWEEN 0 AND 1),
    cpu_usage NUMERIC(10, 6),
    gateway_cpu_usage NUMERIC(10, 6),
    memory_usage NUMERIC(10, 6),
    gateway_memory_usage NUMERIC(10, 6),
    redis_latency_ms NUMERIC(14, 3),
    sla_violation_count BIGINT,
    fairness_index NUMERIC(10, 6)
        CHECK (fairness_index IS NULL OR fairness_index BETWEEN 0 AND 1),
    fairness_basis VARCHAR(60),
    tenant_fairness_details JSONB,
    allocation_proposal_fairness_index NUMERIC(10, 6)
        CHECK (
            allocation_proposal_fairness_index IS NULL
            OR allocation_proposal_fairness_index BETWEEN 0 AND 1
        ),
    policy_changes INTEGER,
    stabilization_time_seconds NUMERIC(14, 3),
    redis_commands_per_second NUMERIC(14, 3),
    redis_connection_count INTEGER,
    redis_memory_bytes BIGINT,
    redis_error_count BIGINT,
    redis_hot_key_observation TEXT,
    forecast_mae NUMERIC(14, 6),
    forecast_wape NUMERIC(14, 6),
    recommendation_generation_ms NUMERIC(14, 3),
    policy_application_ms NUMERIC(14, 3),
    propagation_delay_ms NUMERIC(14, 3),
    oscillation_frequency NUMERIC(14, 6),
    prometheus_query_reference TEXT,
    metrics_collection_errors JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at TIMESTAMPTZ NOT NULL
);

CREATE INDEX idx_benchmark_results_run
    ON benchmark_results(run_id);
