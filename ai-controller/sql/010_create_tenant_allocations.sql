CREATE TABLE tenant_allocation_configs (
    id UUID PRIMARY KEY,
    service_key VARCHAR(100) NOT NULL,
    tenant_id VARCHAR(128) NOT NULL,
    priority INTEGER NOT NULL CHECK (priority >= 1),
    weight NUMERIC(14, 3) NOT NULL CHECK (weight > 0),
    minimum_rate NUMERIC(14, 3) NOT NULL CHECK (minimum_rate >= 0),
    maximum_rate NUMERIC(14, 3) NOT NULL CHECK (maximum_rate > 0),
    adaptive_enabled BOOLEAN NOT NULL DEFAULT TRUE,
    predicted_demand NUMERIC(14, 3) NOT NULL DEFAULT 0
        CHECK (predicted_demand >= 0),
    current_allocation NUMERIC(14, 3) NOT NULL DEFAULT 0
        CHECK (current_allocation >= 0),
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT uq_tenant_allocation_config_service_tenant
        UNIQUE (service_key, tenant_id),
    CONSTRAINT ck_tenant_allocation_config_bounds
        CHECK (minimum_rate <= maximum_rate)
);

CREATE INDEX idx_tenant_allocation_configs_service
    ON tenant_allocation_configs(service_key);

CREATE TABLE tenant_allocation_runs (
    id UUID PRIMARY KEY,
    service_key VARCHAR(100) NOT NULL,
    allocation_version BIGINT NOT NULL CHECK (allocation_version > 0),
    global_capacity NUMERIC(14, 3) NOT NULL CHECK (global_capacity > 0),
    evaluation_metrics JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT uq_tenant_allocation_run_service_version
        UNIQUE (service_key, allocation_version)
);

CREATE INDEX idx_tenant_allocation_runs_service_created
    ON tenant_allocation_runs(service_key, created_at DESC);

CREATE TABLE tenant_allocation_results (
    id UUID PRIMARY KEY,
    allocation_run_id UUID NOT NULL
        REFERENCES tenant_allocation_runs(id),
    service_key VARCHAR(100) NOT NULL,
    tenant_id VARCHAR(128) NOT NULL,
    allocation_rate NUMERIC(14, 3) NOT NULL CHECK (allocation_rate >= 0),
    predicted_demand NUMERIC(14, 3) NOT NULL CHECK (predicted_demand >= 0),
    current_allocation NUMERIC(14, 3) NOT NULL CHECK (current_allocation >= 0),
    priority INTEGER NOT NULL CHECK (priority >= 1),
    weight NUMERIC(14, 3) NOT NULL CHECK (weight > 0),
    minimum_rate NUMERIC(14, 3) NOT NULL CHECK (minimum_rate >= 0),
    maximum_rate NUMERIC(14, 3) NOT NULL CHECK (maximum_rate > 0),
    adaptive_enabled BOOLEAN NOT NULL,
    global_capacity NUMERIC(14, 3) NOT NULL CHECK (global_capacity > 0),
    allocation_version BIGINT NOT NULL CHECK (allocation_version > 0),
    created_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT uq_tenant_allocation_result_run_tenant
        UNIQUE (allocation_run_id, tenant_id)
);

CREATE INDEX idx_tenant_allocation_results_service_created
    ON tenant_allocation_results(service_key, created_at DESC);
