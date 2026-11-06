from collections.abc import Sequence
import numpy as np
from sklearn.metrics import mean_absolute_error, root_mean_squared_error

from app.forecasting.baseline_models import (
    ExponentialSmoothingForecaster,
    MovingAverageForecaster,
)
from app.forecasting.holt_model import HoltTrafficForecaster
from app.forecasting.schemas import ModelAccuracy

MODEL_FACTORIES = (
    MovingAverageForecaster,
    ExponentialSmoothingForecaster,
    HoltTrafficForecaster,
)


def rolling_origin_evaluation(
    values: Sequence[float],
    *,
    horizons_steps: dict[int, int],
    minimum_history: int = 20,
) -> list[ModelAccuracy]:
    series = np.asarray(values, dtype=float)
    if series.ndim != 1 or not np.isfinite(series).all() or (series < 0).any():
        raise ValueError("Evaluation data must be finite and non-negative")
    if len(series) <= minimum_history:
        raise ValueError("Insufficient telemetry history for evaluation")

    errors: dict[tuple[str, int], list[tuple[np.ndarray, np.ndarray]]] = {}
    for model_factory in MODEL_FACTORIES:
        for horizon_seconds, steps in horizons_steps.items():
            errors[(model_factory.name, horizon_seconds)] = []
        for origin in range(minimum_history, len(series)):
            for horizon_seconds, steps in horizons_steps.items():
                if origin + steps > len(series):
                    continue
                try:
                    predictions = model_factory().forecast(series[:origin], steps)
                except (ValueError, ArithmeticError):
                    continue
                actual = series[origin : origin + steps]
                errors[(model_factory.name, horizon_seconds)].append(
                    (actual, np.asarray(predictions, dtype=float))
                )

    results: list[ModelAccuracy] = []
    for model_factory in MODEL_FACTORIES:
        for horizon_seconds, _ in horizons_steps.items():
            windows = errors[(model_factory.name, horizon_seconds)]
            if not windows:
                continue
            actual = np.concatenate([window[0] for window in windows])
            predicted = np.concatenate([window[1] for window in windows])
            absolute_errors = np.abs(actual - predicted)
            total_actual = float(np.abs(actual).sum())
            peak_errors = [
                abs(float(np.max(observed)) - float(np.max(forecast)))
                for observed, forecast in windows
            ]
            spike_threshold = float(np.quantile(actual, 0.9))
            low_threshold = float(np.quantile(actual, 0.25))
            spike_errors = absolute_errors[actual >= spike_threshold]
            low_errors = absolute_errors[actual <= low_threshold]
            results.append(
                ModelAccuracy(
                    model_name=model_factory.name,
                    horizon_seconds=horizon_seconds,
                    sample_count=len(actual),
                    mae=float(mean_absolute_error(actual, predicted)),
                    rmse=float(root_mean_squared_error(actual, predicted)),
                    wape_percent=(
                        float(absolute_errors.sum() / total_actual * 100)
                        if total_actual > 0
                        else None
                    ),
                    peak_prediction_error=float(np.mean(peak_errors)),
                    spike_mae=(
                        float(spike_errors.mean()) if len(spike_errors) else None
                    ),
                    low_traffic_mae=(
                        float(low_errors.mean()) if len(low_errors) else None
                    ),
                )
            )
    return results
