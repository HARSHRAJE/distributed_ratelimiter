from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram

REGISTRY = CollectorRegistry()

FORECAST_GENERATION_SECONDS = Histogram(
    "ai_controller_forecast_generation_seconds",
    "Time spent generating traffic forecasts",
    ("service_key",),
    registry=REGISTRY,
)
FORECAST_FAILURES = Counter(
    "ai_controller_forecast_failures_total",
    "Failed traffic forecast attempts",
    ("service_key",),
    registry=REGISTRY,
)
FORECAST_MAE = Gauge(
    "ai_controller_forecast_mae",
    "Rolling-origin forecast mean absolute error in RPS",
    ("service_key", "model", "horizon_seconds"),
    registry=REGISTRY,
)
FORECAST_WAPE = Gauge(
    "ai_controller_forecast_wape_percent",
    "Rolling-origin forecast weighted absolute percentage error",
    ("service_key", "model", "horizon_seconds"),
    registry=REGISTRY,
)
FORECAST_DEVIATION = Gauge(
    "ai_controller_forecast_to_actual_deviation_rps",
    "Rolling-origin forecast absolute deviation from actual RPS",
    ("service_key", "model", "horizon_seconds"),
    registry=REGISTRY,
)
FORECAST_FRESHNESS = Gauge(
    "ai_controller_forecast_data_freshness_seconds",
    "Age of the latest telemetry observation used for forecasting",
    ("service_key",),
    registry=REGISTRY,
)
FORECAST_PREDICTED_RPS = Gauge(
    "ai_controller_forecast_predicted_rps",
    "Latest predicted incoming RPS by forecast horizon",
    ("service_key", "model", "horizon_seconds"),
    registry=REGISTRY,
)
FORECAST_ACTUAL_RPS = Gauge(
    "ai_controller_forecast_actual_rps",
    "Latest observed incoming RPS for comparison with forecasts",
    ("service_key",),
    registry=REGISTRY,
)
RECOMMENDATION_GENERATION_SECONDS = Histogram(
    "ai_controller_recommendation_generation_seconds",
    "Time spent generating a policy recommendation",
    ("service_key",),
    registry=REGISTRY,
)
FORECAST_MODEL_INFO = Gauge(
    "ai_controller_forecast_model_info",
    "Forecast model version information",
    ("service_key", "model", "version"),
    registry=REGISTRY,
)
ROLLBACK_FAILURES = Counter(
    "ai_controller_rollback_failures_total",
    "Rollback attempts that failed before Redis synchronization",
    ("service_key", "reason"),
    registry=REGISTRY,
)
BREAKER_STATE = Gauge(
    "ai_controller_circuit_breaker_state",
    "Durable adaptive-control breaker state (one active state per service)",
    ("service_key", "state"),
    registry=REGISTRY,
)
