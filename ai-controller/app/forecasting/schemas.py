from datetime import datetime
import math
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ForecastInput(BaseModel):
    service_key: str = Field(min_length=1, max_length=100)
    timestamps: list[datetime] = Field(min_length=20)
    incoming_rps: list[float | None] = Field(min_length=20)
    allowed_rps: list[float | None] = Field(min_length=20)
    rejected_rps: list[float | None] = Field(min_length=20)
    p95_latency_ms: list[float | None] | None = None

    @model_validator(mode="after")
    def validate_observation_lengths(self) -> "ForecastInput":
        lengths = {
            len(self.timestamps),
            len(self.incoming_rps),
            len(self.allowed_rps),
            len(self.rejected_rps),
        }
        if self.p95_latency_ms is not None:
            lengths.add(len(self.p95_latency_ms))
        if len(lengths) != 1:
            raise ValueError("All observation arrays must have equal lengths")
        numeric_series = [
            self.incoming_rps,
            self.allowed_rps,
            self.rejected_rps,
        ]
        if self.p95_latency_ms is not None:
            numeric_series.append(self.p95_latency_ms)
        if any(
            value is not None and (not math.isfinite(value) or value < 0)
            for series in numeric_series
            for value in series
        ):
            raise ValueError("Observation values must be non-negative")
        if any(
            current <= previous
            for previous, current in zip(
                self.timestamps,
                self.timestamps[1:],
            )
        ):
            raise ValueError("Timestamps must be strictly increasing")
        return self


class ForecastRequest(BaseModel):
    horizons_seconds: list[int] = Field(default_factory=lambda: [30, 60])

    @model_validator(mode="after")
    def validate_horizons(self) -> "ForecastRequest":
        if not self.horizons_seconds or any(
            value not in (30, 60) for value in self.horizons_seconds
        ):
            raise ValueError("Forecast horizons must be 30 or 60 seconds")
        if len(set(self.horizons_seconds)) != len(self.horizons_seconds):
            raise ValueError("Forecast horizons must be unique")
        return self


class TrafficForecast(BaseModel):
    service_key: str
    forecast_generated_at: datetime
    target_timestamp: datetime
    horizon_seconds: int
    predicted_rps: float = Field(ge=0)
    model_name: str
    model_version: str
    lower_bound: float | None = None
    upper_bound: float | None = None

    model_config = ConfigDict(from_attributes=True)


class ForecastResults(BaseModel):
    service_key: str
    forecasts: list[TrafficForecast]


class ModelAccuracy(BaseModel):
    model_name: str
    horizon_seconds: int
    sample_count: int
    mae: float
    rmse: float
    wape_percent: float | None
    peak_prediction_error: float
    spike_mae: float | None
    low_traffic_mae: float | None


class ForecastAccuracy(BaseModel):
    service_key: str
    evaluation_method: Literal["rolling_origin"]
    models: list[ModelAccuracy]
