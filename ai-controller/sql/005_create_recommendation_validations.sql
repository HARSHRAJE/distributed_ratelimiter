CREATE TABLE recommendation_validations (
    id UUID PRIMARY KEY,
    recommendation_id UUID NOT NULL
        REFERENCES policy_recommendations(id),
    status VARCHAR(20) NOT NULL CHECK (status IN ('VALID', 'REJECTED')),
    validation_result JSONB NOT NULL,
    validated_at TIMESTAMPTZ NOT NULL,
    validator_version VARCHAR(20) NOT NULL
);

CREATE INDEX idx_recommendation_validations_recommendation_time
    ON recommendation_validations(recommendation_id, validated_at DESC);
