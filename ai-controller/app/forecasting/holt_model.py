from collections.abc import Sequence

import numpy as np
from statsmodels.tsa.holtwinters import Holt


class HoltTrafficForecaster:
    name = "holt_linear"

    def forecast(self, values: Sequence[float], steps: int = 4) -> list[float]:
        if steps < 1:
            raise ValueError("steps must be positive")
        series = np.asarray(values, dtype=float)
        if series.ndim != 1 or len(series) < 20:
            raise ValueError("Insufficient telemetry history")
        if not np.isfinite(series).all() or (series < 0).any():
            raise ValueError("Telemetry values must be finite and non-negative")
        fitted = Holt(
            series,
            initialization_method="estimated",
        ).fit(optimized=True)
        return [max(0.0, float(value)) for value in fitted.forecast(steps)]
