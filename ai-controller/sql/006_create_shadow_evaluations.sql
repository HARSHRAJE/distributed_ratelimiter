CREATE TABLE shadow_evaluations (
    id UUID PRIMARY KEY,
    recommendation_id UUID NOT NULL
        REFERENCES policy_recommendations(id),
    service_key VARCHAR(100) NOT NULL,
    current_policy_version BIGINT NOT NULL CHECK (current_policy_version > 0),
    current_rate NUMERIC(14, 3) NOT NULL CHECK (current_rate > 0),
    proposed_rate NUMERIC(14, 3) NOT NULL CHECK (proposed_rate > 0),
    actual_incoming_rps NUMERIC(14, 3) NOT NULL
        CHECK (actual_incoming_rps >= 0),
    estimated_admitted_rps NUMERIC(14, 3) NOT NULL
        CHECK (estimated_admitted_rps >= 0),
    estimated_rejected_rps NUMERIC(14, 3) NOT NULL
        CHECK (estimated_rejected_rps >= 0),
    evaluation_window_seconds INTEGER NOT NULL
        CHECK (evaluation_window_seconds > 0),
    evaluation_result JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL
);

CREATE INDEX idx_shadow_evaluations_service_created
    ON shadow_evaluations(service_key, created_at DESC);
