ALTER TABLE policy_outbox_events
ADD COLUMN locked_until TIMESTAMPTZ;

CREATE INDEX idx_outbox_processing_lease
ON policy_outbox_events(status, locked_until);
