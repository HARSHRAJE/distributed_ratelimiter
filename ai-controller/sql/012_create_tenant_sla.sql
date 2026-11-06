CREATE TABLE tenant_sla_configs (
    id UUID PRIMARY KEY,
    service_key VARCHAR(100) NOT NULL,
    tenant_id VARCHAR(128) NOT NULL,
    tier VARCHAR(20) NOT NULL CHECK (
        tier IN ('BASIC', 'PRO', 'ENTERPRISE')
    ),
    priority INTEGER NOT NULL CHECK (priority >= 1),
    allocation_weight NUMERIC(14, 3) NOT NULL CHECK (allocation_weight > 0),
    minimum_guaranteed_rate NUMERIC(14, 3) NOT NULL
        CHECK (minimum_guaranteed_rate >= 0),
    maximum_rate NUMERIC(14, 3) NOT NULL CHECK (maximum_rate > 0),
    max_throttle_ratio NUMERIC(8, 6) NOT NULL
        CHECK (max_throttle_ratio BETWEEN 0 AND 1),
    tenant_burst_capacity INTEGER NOT NULL CHECK (tenant_burst_capacity > 0),
    availability_target NUMERIC(8, 6) NOT NULL
        CHECK (availability_target > 0 AND availability_target <= 1),
    adaptive_enabled BOOLEAN NOT NULL,
    predicted_demand NUMERIC(14, 3) NOT NULL DEFAULT 0
        CHECK (predicted_demand >= 0),
    config_version BIGINT NOT NULL CHECK (config_version > 0),
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT uq_tenant_sla_service_tenant UNIQUE (service_key, tenant_id),
    CONSTRAINT ck_tenant_sla_rate_bounds
        CHECK (minimum_guaranteed_rate <= maximum_rate)
);

CREATE INDEX idx_tenant_sla_configs_service_tenant
    ON tenant_sla_configs(service_key, tenant_id);

CREATE TABLE tenant_sla_config_versions (
    id UUID PRIMARY KEY,
    config_id UUID NOT NULL REFERENCES tenant_sla_configs(id),
    service_key VARCHAR(100) NOT NULL,
    tenant_id VARCHAR(128) NOT NULL,
    config_version BIGINT NOT NULL CHECK (config_version > 0),
    tier VARCHAR(20) NOT NULL CHECK (
        tier IN ('BASIC', 'PRO', 'ENTERPRISE')
    ),
    priority INTEGER NOT NULL CHECK (priority >= 1),
    allocation_weight NUMERIC(14, 3) NOT NULL CHECK (allocation_weight > 0),
    minimum_guaranteed_rate NUMERIC(14, 3) NOT NULL
        CHECK (minimum_guaranteed_rate >= 0),
    maximum_rate NUMERIC(14, 3) NOT NULL CHECK (maximum_rate > 0),
    max_throttle_ratio NUMERIC(8, 6) NOT NULL
        CHECK (max_throttle_ratio BETWEEN 0 AND 1),
    tenant_burst_capacity INTEGER NOT NULL CHECK (tenant_burst_capacity > 0),
    availability_target NUMERIC(8, 6) NOT NULL
        CHECK (availability_target > 0 AND availability_target <= 1),
    adaptive_enabled BOOLEAN NOT NULL,
    predicted_demand NUMERIC(14, 3) NOT NULL CHECK (predicted_demand >= 0),
    created_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT uq_tenant_sla_config_version
        UNIQUE (config_id, config_version),
    CONSTRAINT ck_tenant_sla_version_rate_bounds
        CHECK (minimum_guaranteed_rate <= maximum_rate)
);

CREATE INDEX idx_tenant_sla_versions_config_created
    ON tenant_sla_config_versions(config_id, created_at DESC);

CREATE TABLE tenant_sla_allocation_runs (
    id UUID PRIMARY KEY,
    service_key VARCHAR(100) NOT NULL,
    allocation_version BIGINT NOT NULL CHECK (allocation_version > 0),
    global_capacity NUMERIC(14, 3) NOT NULL CHECK (global_capacity > 0),
    evaluation_metrics JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT uq_tenant_sla_run_service_version
        UNIQUE (service_key, allocation_version)
);

CREATE INDEX idx_tenant_sla_runs_service_created
    ON tenant_sla_allocation_runs(service_key, created_at DESC);

CREATE TABLE tenant_sla_allocation_results (
    id UUID PRIMARY KEY,
    allocation_run_id UUID NOT NULL
        REFERENCES tenant_sla_allocation_runs(id),
    config_version_id UUID NOT NULL
        REFERENCES tenant_sla_config_versions(id),
    service_key VARCHAR(100) NOT NULL,
    tenant_id VARCHAR(128) NOT NULL,
    config_version BIGINT NOT NULL CHECK (config_version > 0),
    tier VARCHAR(20) NOT NULL CHECK (
        tier IN ('BASIC', 'PRO', 'ENTERPRISE')
    ),
    priority INTEGER NOT NULL CHECK (priority >= 1),
    allocation_weight NUMERIC(14, 3) NOT NULL CHECK (allocation_weight > 0),
    guaranteed_rate NUMERIC(14, 3) NOT NULL CHECK (guaranteed_rate >= 0),
    allocated_rate NUMERIC(14, 3) NOT NULL CHECK (allocated_rate >= 0),
    maximum_rate NUMERIC(14, 3) NOT NULL CHECK (maximum_rate > 0),
    predicted_demand NUMERIC(14, 3) NOT NULL CHECK (predicted_demand >= 0),
    max_throttle_ratio NUMERIC(8, 6) NOT NULL
        CHECK (max_throttle_ratio BETWEEN 0 AND 1),
    tenant_burst_capacity INTEGER NOT NULL CHECK (tenant_burst_capacity > 0),
    availability_target NUMERIC(8, 6) NOT NULL
        CHECK (availability_target > 0 AND availability_target <= 1),
    adaptive_enabled BOOLEAN NOT NULL,
    projected_throttle_ratio NUMERIC(8, 6) NOT NULL
        CHECK (projected_throttle_ratio BETWEEN 0 AND 1),
    resource_usage NUMERIC(20, 6),
    created_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT uq_tenant_sla_result_run_tenant
        UNIQUE (allocation_run_id, tenant_id)
);

CREATE INDEX idx_tenant_sla_results_service_tenant_created
    ON tenant_sla_allocation_results(service_key, tenant_id, created_at DESC);
