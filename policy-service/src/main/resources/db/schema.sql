
CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE services (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    service_key VARCHAR(100) NOT NULL UNIQUE,
    global_capacity INTEGER NOT NULL CHECK (global_capacity > 0),
    global_refill_rate NUMERIC(12, 3) NOT NULL
        CHECK (global_refill_rate > 0),
    config_version BIGINT NOT NULL DEFAULT 1
        CHECK (config_version > 0),
    hard_max_refill_rate NUMERIC(12, 3) NOT NULL
        CHECK (hard_max_refill_rate > 0),
    adaptive_enabled BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CHECK (global_refill_rate <= hard_max_refill_rate)
);

CREATE TABLE rate_limit_policies (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    service_id UUID NOT NULL REFERENCES services(id),
    tenant_id VARCHAR(128) NOT NULL,
    route_id VARCHAR(128) NOT NULL,
    active_version BIGINT,
    sync_revision BIGINT NOT NULL DEFAULT 1
        CHECK (sync_revision > 0),
    status VARCHAR(20) NOT NULL DEFAULT 'ACTIVE'
        CHECK (status IN ('ACTIVE', 'DISABLED')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (service_id, tenant_id, route_id)
);

CREATE TABLE rate_limit_policy_versions (
    policy_id UUID NOT NULL REFERENCES rate_limit_policies(id),
    version BIGINT NOT NULL CHECK (version > 0),
    tenant_capacity INTEGER NOT NULL CHECK (tenant_capacity > 0),
    tenant_refill_rate NUMERIC(12, 3) NOT NULL
        CHECK (tenant_refill_rate > 0),
    route_capacity INTEGER NOT NULL CHECK (route_capacity > 0),
    route_refill_rate NUMERIC(12, 3) NOT NULL
        CHECK (route_refill_rate > 0),
    min_refill_rate NUMERIC(12, 3) NOT NULL
        CHECK (min_refill_rate > 0),
    max_refill_rate NUMERIC(12, 3) NOT NULL
        CHECK (max_refill_rate >= min_refill_rate),
    source VARCHAR(20) NOT NULL
        CHECK (source IN ('MANUAL', 'AI', 'ROLLBACK')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    created_by VARCHAR(128) NOT NULL,
    PRIMARY KEY (policy_id, version)
);

ALTER TABLE rate_limit_policies
    ADD CONSTRAINT fk_policy_active_version
    FOREIGN KEY (id, active_version)
    REFERENCES rate_limit_policy_versions (policy_id, version);
