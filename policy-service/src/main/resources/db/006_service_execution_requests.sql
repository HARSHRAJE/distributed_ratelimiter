CREATE TABLE service_execution_requests (
    execution_id UUID PRIMARY KEY,
    service_id UUID NOT NULL REFERENCES services(id),
    expected_version BIGINT NOT NULL CHECK (expected_version > 0),
    resulting_version BIGINT NOT NULL CHECK (resulting_version > expected_version),
    global_capacity INTEGER NOT NULL CHECK (global_capacity > 0),
    global_refill_rate NUMERIC(12, 3) NOT NULL
        CHECK (global_refill_rate > 0),
    accepted_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_service_execution_requests_service
    ON service_execution_requests(service_id, accepted_at DESC);
