CREATE TABLE route_allocation_configs (
    id UUID PRIMARY KEY,
    service_key VARCHAR(100) NOT NULL,
    tenant_id VARCHAR(128) NOT NULL,
    route_id VARCHAR(128) NOT NULL,
    route_weight NUMERIC(14, 3) NOT NULL CHECK (route_weight > 0),
    minimum_rate NUMERIC(14, 3) NOT NULL CHECK (minimum_rate >= 0),
    maximum_rate NUMERIC(14, 3) NOT NULL CHECK (maximum_rate > 0),
    resource_cost_factor NUMERIC(14, 6) NOT NULL
        CHECK (resource_cost_factor > 0),
    predicted_demand NUMERIC(14, 3) NOT NULL CHECK (predicted_demand >= 0),
    priority INTEGER NOT NULL DEFAULT 1 CHECK (priority >= 1),
    adaptive_enabled BOOLEAN NOT NULL DEFAULT TRUE,
    current_allocation NUMERIC(14, 3) NOT NULL DEFAULT 0
        CHECK (current_allocation >= 0),
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT uq_route_allocation_config_scope
        UNIQUE (service_key, tenant_id, route_id),
    CONSTRAINT ck_route_allocation_config_bounds
        CHECK (minimum_rate <= maximum_rate)
);

CREATE INDEX idx_route_allocation_configs_service_tenant_route
    ON route_allocation_configs(service_key, tenant_id, route_id);

CREATE TABLE route_allocation_runs (
    id UUID PRIMARY KEY,
    service_key VARCHAR(100) NOT NULL,
    allocation_version BIGINT NOT NULL CHECK (allocation_version > 0),
    tenant_allocation_run_id UUID NOT NULL
        REFERENCES tenant_allocation_runs(id),
    global_capacity NUMERIC(14, 3) NOT NULL CHECK (global_capacity > 0),
    backend_resource_budget NUMERIC(14, 3) NOT NULL
        CHECK (backend_resource_budget > 0),
    evaluation_metrics JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT uq_route_allocation_run_service_version
        UNIQUE (service_key, allocation_version)
);

CREATE INDEX idx_route_allocation_runs_service_created
    ON route_allocation_runs(service_key, created_at DESC);

CREATE TABLE route_allocation_results (
    id UUID PRIMARY KEY,
    allocation_run_id UUID NOT NULL
        REFERENCES route_allocation_runs(id),
    service_key VARCHAR(100) NOT NULL,
    tenant_id VARCHAR(128) NOT NULL,
    route_id VARCHAR(128) NOT NULL,
    allocated_rate NUMERIC(14, 3) NOT NULL CHECK (allocated_rate >= 0),
    predicted_demand NUMERIC(14, 3) NOT NULL CHECK (predicted_demand >= 0),
    estimated_resource_usage NUMERIC(20, 6) NOT NULL
        CHECK (estimated_resource_usage >= 0),
    tenant_allocation_limit NUMERIC(14, 3) NOT NULL
        CHECK (tenant_allocation_limit >= 0),
    route_weight NUMERIC(14, 3) NOT NULL CHECK (route_weight > 0),
    resource_cost_factor NUMERIC(14, 6) NOT NULL
        CHECK (resource_cost_factor > 0),
    priority INTEGER NOT NULL CHECK (priority >= 1),
    minimum_rate NUMERIC(14, 3) NOT NULL CHECK (minimum_rate >= 0),
    maximum_rate NUMERIC(14, 3) NOT NULL CHECK (maximum_rate > 0),
    adaptive_enabled BOOLEAN NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT uq_route_allocation_result_run_scope
        UNIQUE (allocation_run_id, tenant_id, route_id),
    CONSTRAINT ck_route_allocation_result_bounds
        CHECK (minimum_rate <= maximum_rate)
);

CREATE INDEX idx_route_allocation_results_service_tenant_route
    ON route_allocation_results(service_key, tenant_id, route_id);
CREATE INDEX idx_route_allocation_results_service_created
    ON route_allocation_results(service_key, created_at DESC);
