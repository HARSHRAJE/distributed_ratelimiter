from datetime import datetime, timedelta, timezone
from uuid import uuid4

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from app.config import Settings
from app.forecasting.baseline_models import (
    ExponentialSmoothingForecaster,
    MovingAverageForecaster,
)
from app.forecasting.evaluation import rolling_origin_evaluation
from app.forecasting.feature_engineering import calculate_features
from app.forecasting.holt_model import HoltTrafficForecaster
from app.main import create_app
from app.telemetry.models import Base, TelemetrySampleRecord


def test_features_preserve_missing_data_and_handle_zero_denominators() -> None:
    frame = pd.DataFrame(
        {
            "incoming_rps": [0.0, 5.0, None, 10.0, *([10.0] * 16)],
            "rejected_rps": [0.0, 0.0, 0.0, 1.0, *([1.0] * 16)],
            "p95_latency_ms": [10.0, 11.0, 12.0, 13.0, *([13.0] * 16)],
        }
    )

    features = calculate_features(frame)

    assert np.isnan(features.loc[0, "rejection_ratio"])
    assert np.isnan(features.loc[1, "rps_change"])
    assert np.isnan(features.loc[2, "incoming_rps"])
    assert np.isnan(features.loc[2, "rps_avg_1m"])
    assert features.loc[3, "rejection_ratio"] == pytest.approx(0.1)
    assert features.loc[3, "latency_trend"] == 1.0
    assert np.isnan(features.loc[20 - 1, "rps_avg_5m"])


@pytest.mark.parametrize(
    "forecaster",
    [
        MovingAverageForecaster(),
        ExponentialSmoothingForecaster(),
        HoltTrafficForecaster(),
    ],
)
def test_forecasters_return_non_negative_finite_predictions(forecaster) -> None:
    predictions = forecaster.forecast(np.linspace(10, 20, 24), steps=4)

    assert len(predictions) == 4
    assert all(np.isfinite(value) and value >= 0 for value in predictions)


def test_rolling_origin_evaluation_compares_all_models_and_horizons() -> None:
    values = np.asarray([10 + index * 0.2 for index in range(32)])

    results = rolling_origin_evaluation(
        values,
        horizons_steps={30: 2, 60: 4},
        minimum_history=20,
    )

    assert len(results) == 6
    assert {result.model_name for result in results} == {
        "moving_average",
        "exponential_smoothing",
        "holt_linear",
    }
    assert {result.horizon_seconds for result in results} == {30, 60}
    assert all(result.sample_count > 0 and result.mae >= 0 for result in results)


def test_forecast_api_generates_persists_and_protects_results() -> None:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    now = datetime.now(timezone.utc)
    with engine.begin() as connection:
        connection.execute(
            TelemetrySampleRecord.__table__.insert(),
            [
                {
                    "id": uuid4(),
                    "service_key": "orders-service",
                    "window_start": now - timedelta(seconds=15 * offset),
                    "window_seconds": 15,
                    "incoming_rps": 50 + offset,
                    "allowed_rps": 45 + offset,
                    "rejected_rps": 5,
                    "p95_latency_ms": 10,
                    "p99_latency_ms": 20,
                    "error_rate": 0,
                    "cpu_utilization": None,
                    "memory_utilization": None,
                    "redis_latency_ms": None,
                    "queue_depth": 0,
                    "data_quality": "valid",
                    "collected_at": now - timedelta(seconds=15 * offset),
                }
                for offset in range(40, 0, -1)
            ],
        )
    settings = Settings(
        prometheus_url="http://prometheus:9090",
        service_keys=("orders-service",),
        collection_interval_seconds=15,
        stale_after_seconds=60,
        aggregation_window_seconds=300,
        prometheus_timeout_seconds=5,
        api_key="c" * 32,
        db_host="localhost",
        db_port=5432,
        db_name="test",
        db_username="test",
        db_password="test",
    )
    app = create_app(settings, engine)

    with TestClient(app) as client:
        assert client.get("/api/v1/forecast/latest/orders-service").status_code == 401
        headers = {"X-Internal-API-Key": "c" * 32}
        generated = client.post(
            "/api/v1/forecast/orders-service",
            headers=headers,
        )
        assert generated.status_code == 200, generated.text
        assert len(generated.json()["forecasts"]) == 6
        assert client.get(
            "/api/v1/forecast/latest/orders-service",
            headers=headers,
        ).status_code == 200
        history = client.get(
            "/api/v1/forecast/history/orders-service",
            headers=headers,
        )
        assert len(history.json()["forecasts"]) == 6
        accuracy = client.get(
            "/api/v1/forecast/accuracy/orders-service",
            headers=headers,
        )
        assert accuracy.status_code == 200, accuracy.text
        assert len(accuracy.json()["models"]) == 6
        assert "ai_controller_forecast_predicted_rps" in client.get(
            "/metrics"
        ).text

    engine.dispose()
