CREATE TABLE telemetry_samples (
    id UUID PRIMARY KEY,
    service_key VARCHAR(100) NOT NULL,
    window_start TIMESTAMPTZ NOT NULL,
    window_seconds INTEGER NOT NULL CHECK (window_seconds > 0),

    incoming_rps NUMERIC(14, 3),
    allowed_rps NUMERIC(14, 3),
    rejected_rps NUMERIC(14, 3),

    p95_latency_ms NUMERIC(14, 3),
    p99_latency_ms NUMERIC(14, 3),

    error_rate NUMERIC(10, 6),
    cpu_utilization NUMERIC(7, 3),
    memory_utilization NUMERIC(7, 3),
    redis_latency_ms NUMERIC(14, 3),
    queue_depth NUMERIC(14, 3),

    data_quality VARCHAR(20) NOT NULL
        CHECK (data_quality IN ('valid', 'partial', 'stale', 'missing', 'invalid')),
    collected_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT uq_telemetry_sample_window
        UNIQUE (service_key, window_start, window_seconds)
);

CREATE INDEX idx_telemetry_service_time
    ON telemetry_samples(service_key, window_start DESC);

CREATE TABLE telemetry_windows (
    id UUID PRIMARY KEY,
    service_key VARCHAR(100) NOT NULL,
    window_start TIMESTAMPTZ NOT NULL,
    window_seconds INTEGER NOT NULL CHECK (window_seconds > 0),

    mean_incoming_rps NUMERIC(14, 3),
    max_incoming_rps NUMERIC(14, 3),
    mean_allowed_rps NUMERIC(14, 3),
    mean_rejected_rps NUMERIC(14, 3),
    mean_p95_latency_ms NUMERIC(14, 3),
    max_p95_latency_ms NUMERIC(14, 3),
    mean_p99_latency_ms NUMERIC(14, 3),
    max_p99_latency_ms NUMERIC(14, 3),
    mean_error_rate NUMERIC(10, 6),
    missing_sample_count INTEGER NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT uq_telemetry_aggregate_window
        UNIQUE (service_key, window_start, window_seconds)
);

CREATE INDEX idx_telemetry_window_service_time
    ON telemetry_windows(service_key, window_start DESC);

CREATE TABLE telemetry_collection_status (
    service_key VARCHAR(100) PRIMARY KEY,
    state VARCHAR(20) NOT NULL
        CHECK (state IN ('idle', 'success', 'failed', 'stale')),
    last_attempt_at TIMESTAMPTZ,
    last_success_at TIMESTAMPTZ,
    last_quality VARCHAR(20),
    last_error VARCHAR(100),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
