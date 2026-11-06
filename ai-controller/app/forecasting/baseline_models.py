from collections.abc import Sequence

import numpy as np
from statsmodels.tsa.holtwinters import SimpleExpSmoothing


class MovingAverageForecaster:
    name = "moving_average"

    def forecast(self, values: Sequence[float], steps: int = 4) -> list[float]:
        series = _validate(values, steps)
        prediction = float(np.mean(series[-4:]))
        return [max(0.0, prediction)] * steps


class ExponentialSmoothingForecaster:
    name = "exponential_smoothing"

    def forecast(self, values: Sequence[float], steps: int = 4) -> list[float]:
        series = _validate(values, steps)
        fitted = SimpleExpSmoothing(
            series,
            initialization_method="estimated",
        ).fit(optimized=True)
        return [max(0.0, float(value)) for value in fitted.forecast(steps)]


def _validate(values: Sequence[float], steps: int) -> np.ndarray:
    if steps < 1:
        raise ValueError("steps must be positive")
    series = np.asarray(values, dtype=float)
    if series.ndim != 1 or len(series) < 20:
        raise ValueError("Insufficient telemetry history")
    if not np.isfinite(series).all() or (series < 0).any():
        raise ValueError("Telemetry values must be finite and non-negative")
    return series
