CREATE TABLE adaptive_control_breakers (
    id UUID PRIMARY KEY,
    service_key VARCHAR(100) NOT NULL UNIQUE,
    state VARCHAR(16) NOT NULL CHECK (state IN ('CLOSED', 'OPEN', 'HALF_OPEN')),
    failure_count INTEGER NOT NULL DEFAULT 0 CHECK (failure_count >= 0),
    success_count INTEGER NOT NULL DEFAULT 0 CHECK (success_count >= 0),
    half_open_attempts INTEGER NOT NULL DEFAULT 0 CHECK (half_open_attempts >= 0),
    opened_at TIMESTAMPTZ,
    next_attempt_at TIMESTAMPTZ,
    last_failure_reason TEXT,
    manual_disabled BOOLEAN NOT NULL DEFAULT FALSE,
    updated_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE circuit_breaker_events (
    id UUID PRIMARY KEY,
    service_key VARCHAR(100) NOT NULL,
    from_state VARCHAR(16) NOT NULL CHECK (from_state IN ('CLOSED', 'OPEN', 'HALF_OPEN')),
    to_state VARCHAR(16) NOT NULL CHECK (to_state IN ('CLOSED', 'OPEN', 'HALF_OPEN')),
    reason TEXT NOT NULL,
    actor VARCHAR(32) NOT NULL CHECK (actor IN ('automatic', 'administrator')),
    created_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX idx_circuit_breaker_events_service_created
    ON circuit_breaker_events(service_key, created_at DESC);

CREATE TABLE component_health_breakers (
    id UUID PRIMARY KEY,
    service_key VARCHAR(100) NOT NULL,
    component VARCHAR(32) NOT NULL CHECK (
        component IN ('TELEMETRY', 'FORECASTING', 'POLICY_SERVICE', 'REDIS_SYNC', 'EXECUTION')
    ),
    state VARCHAR(16) NOT NULL CHECK (state IN ('CLOSED', 'OPEN', 'HALF_OPEN')),
    failure_count INTEGER NOT NULL DEFAULT 0 CHECK (failure_count >= 0),
    last_failure_reason TEXT,
    next_attempt_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT uq_component_health_service UNIQUE (service_key, component)
);

CREATE TABLE adaptive_execution_reservations (
    id UUID PRIMARY KEY,
    service_key VARCHAR(100) NOT NULL,
    recommendation_id UUID NOT NULL REFERENCES policy_recommendations(id),
    active BOOLEAN NOT NULL DEFAULT TRUE,
    recovery_check BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL,
    released_at TIMESTAMPTZ,
    CONSTRAINT uq_adaptive_reservation_recommendation
        UNIQUE (service_key, recommendation_id)
);
CREATE INDEX idx_adaptive_reservations_service_active
    ON adaptive_execution_reservations(service_key, active);
