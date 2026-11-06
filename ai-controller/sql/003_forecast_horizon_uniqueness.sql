ALTER TABLE traffic_forecasts
    DROP CONSTRAINT uq_traffic_forecast_target_model;

ALTER TABLE traffic_forecasts
    ADD CONSTRAINT uq_traffic_forecast_target_model_horizon
    UNIQUE (service_key, target_timestamp, model_name, horizon_seconds);
