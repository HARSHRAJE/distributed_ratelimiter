CREATE TABLE policy_audit_logs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    policy_id UUID NOT NULL
        REFERENCES rate_limit_policies(id),

    action VARCHAR(30) NOT NULL CHECK (
        action IN (
            'CREATED',
            'UPDATED',
            'ACTIVATED',
            'DEACTIVATED',
            'ROLLED_BACK'
        )
    ),

    previous_version BIGINT,
    new_version BIGINT,

    actor VARCHAR(128) NOT NULL,
    reason VARCHAR(500),

    occurred_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_policy_audit_policy_time
ON policy_audit_logs(policy_id, occurred_at DESC);
