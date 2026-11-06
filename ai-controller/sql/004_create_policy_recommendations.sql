CREATE TABLE policy_recommendations (
    id UUID PRIMARY KEY,
    service_key VARCHAR(100) NOT NULL,
    scope VARCHAR(20) NOT NULL CHECK (scope = 'GLOBAL'),
    current_rate NUMERIC NOT NULL CHECK (current_rate > 0),
    recommended_rate NUMERIC NOT NULL CHECK (recommended_rate > 0),
    action VARCHAR(20) NOT NULL
        CHECK (action IN ('INCREASE', 'DECREASE', 'HOLD')),
    reason TEXT NOT NULL,
    forecast_rps NUMERIC NOT NULL CHECK (forecast_rps >= 0),
    forecast_confidence NUMERIC NOT NULL
        CHECK (forecast_confidence >= 0 AND forecast_confidence <= 1),
    safe_capacity_rps NUMERIC NOT NULL CHECK (safe_capacity_rps > 0),
    policy_version BIGINT NOT NULL CHECK (policy_version > 0),
    status VARCHAR(20) NOT NULL
        CHECK (status IN ('PENDING', 'ACCEPTED', 'REJECTED', 'EXPIRED')),
    generated_at TIMESTAMPTZ NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    CHECK (expires_at > generated_at)
);

CREATE INDEX idx_recommendations_service_generated
    ON policy_recommendations(service_key, generated_at DESC);
