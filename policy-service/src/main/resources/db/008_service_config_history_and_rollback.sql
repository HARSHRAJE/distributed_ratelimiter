CREATE TABLE service_config_versions (
    id UUID PRIMARY KEY,
    service_id UUID NOT NULL REFERENCES services(id),
    config_version BIGINT NOT NULL CHECK (config_version > 0),
    global_capacity INTEGER NOT NULL CHECK (global_capacity > 0),
    global_refill_rate NUMERIC(12, 3) NOT NULL
        CHECK (global_refill_rate > 0),
    adaptive_enabled BOOLEAN NOT NULL,
    source VARCHAR(32) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_service_config_versions_service_version
        UNIQUE (service_id, config_version)
);

INSERT INTO service_config_versions (
    id, service_id, config_version, global_capacity, global_refill_rate,
    adaptive_enabled, source
)
SELECT gen_random_uuid(), id, config_version, global_capacity,
       global_refill_rate, adaptive_enabled, 'BASELINE'
FROM services
ON CONFLICT (service_id, config_version) DO NOTHING;

CREATE TABLE service_rollback_requests (
    rollback_id UUID PRIMARY KEY,
    service_id UUID NOT NULL REFERENCES services(id),
    expected_active_version BIGINT NOT NULL CHECK (expected_active_version > 0),
    restored_from_version BIGINT NOT NULL CHECK (restored_from_version > 0),
    rollback_version BIGINT NOT NULL CHECK (rollback_version > expected_active_version),
    global_capacity INTEGER NOT NULL CHECK (global_capacity > 0),
    global_refill_rate NUMERIC(12, 3) NOT NULL
        CHECK (global_refill_rate > 0),
    accepted_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
