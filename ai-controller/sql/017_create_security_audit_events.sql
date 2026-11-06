CREATE TABLE security_audit_events (
    id UUID PRIMARY KEY,
    actor_id VARCHAR(128),
    tenant_id VARCHAR(128),
    service_key VARCHAR(100),
    event_type VARCHAR(100) NOT NULL,
    resource_id VARCHAR(128),
    outcome VARCHAR(30) NOT NULL,
    source_ip INET,
    details JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_security_audit_tenant
    ON security_audit_events(tenant_id, created_at DESC);
CREATE INDEX idx_security_audit_type
    ON security_audit_events(event_type, created_at DESC);
