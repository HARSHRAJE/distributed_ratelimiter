ALTER TABLE services
    ADD COLUMN config_version BIGINT NOT NULL DEFAULT 1
    CHECK (config_version > 0);

ALTER TABLE rate_limit_policies
    ADD COLUMN sync_revision BIGINT NOT NULL DEFAULT 1
    CHECK (sync_revision > 0);
