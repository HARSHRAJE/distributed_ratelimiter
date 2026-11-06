CREATE TABLE policy_execution_control (
    id VARCHAR(20) PRIMARY KEY CHECK (id = 'global'),
    kill_switch_active BOOLEAN NOT NULL DEFAULT TRUE,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

INSERT INTO policy_execution_control (id, kill_switch_active)
VALUES ('global', TRUE)
ON CONFLICT (id) DO NOTHING;
