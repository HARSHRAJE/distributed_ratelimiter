CREATE TABLE traffic_forecasts (
    id UUID PRIMARY KEY,
    service_key VARCHAR(100) NOT NULL,

    forecast_generated_at TIMESTAMPTZ NOT NULL,
    target_timestamp TIMESTAMPTZ NOT NULL,
    horizon_seconds INTEGER NOT NULL CHECK (horizon_seconds > 0),

    predicted_rps NUMERIC(14, 3) NOT NULL CHECK (predicted_rps >= 0),
    model_name VARCHAR(100) NOT NULL,
    model_version VARCHAR(50) NOT NULL,

    lower_bound NUMERIC(14, 3),
    upper_bound NUMERIC(14, 3),

    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT uq_traffic_forecast_target_model
        UNIQUE (service_key, target_timestamp, model_name)
);

CREATE INDEX idx_forecasts_service_time
    ON traffic_forecasts(service_key, target_timestamp DESC);
