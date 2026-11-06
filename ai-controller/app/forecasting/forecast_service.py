import logging
import time
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import sessionmaker

from app.circuit_breaker.repository import BreakerRepository
from app.config import Settings
from app.forecasting.baseline_models import (
    ExponentialSmoothingForecaster,
    MovingAverageForecaster,
)
from app.forecasting.evaluation import rolling_origin_evaluation
from app.forecasting.holt_model import HoltTrafficForecaster
from app.forecasting.metrics import (
    FORECAST_ACTUAL_RPS,
    FORECAST_DEVIATION,
    FORECAST_FAILURES,
    FORECAST_FRESHNESS,
    FORECAST_GENERATION_SECONDS,
    FORECAST_MAE,
    FORECAST_MODEL_INFO,
    FORECAST_PREDICTED_RPS,
    FORECAST_WAPE,
)
from app.forecasting.schemas import ModelAccuracy
from app.storage.repositories import ForecastRepository
from app.telemetry.models import TelemetrySampleRecord, TrafficForecastRecord

logger = logging.getLogger("ai_controller.forecasting")
MODEL_VERSION = "1.0"
MINIMUM_HISTORY = 20
MAX_EVALUATION_SAMPLES = 200
FORECASTERS = (
    MovingAverageForecaster,
    ExponentialSmoothingForecaster,
    HoltTrafficForecaster,
)


class ForecastService:
    def __init__(
        self,
        settings: Settings,
        session_factory: sessionmaker,
    ) -> None:
        self.settings = settings
        self.session_factory = session_factory

    def generate(
        self,
        service_key: str,
        horizons_seconds: list[int],
        *,
        generated_at: datetime | None = None,
    ) -> list[TrafficForecastRecord]:
        if service_key not in self.settings.service_keys:
            raise ValueError("Service is not configured for forecasting")
        generated = generated_at or datetime.now(timezone.utc)
        started = time.perf_counter()
        try:
            with self.session_factory() as session:
                repository = ForecastRepository(session)
                observations = repository.telemetry_history(service_key)
                values, latest_at = self._latest_contiguous_values(observations)
                age = max(0.0, (generated - latest_at).total_seconds())
                allowed_age = max(
                    self.settings.stale_after_seconds,
                    self.settings.collection_interval_seconds * 3,
                )
                if age > allowed_age:
                    raise ValueError("Latest telemetry is stale")
                FORECAST_FRESHNESS.labels(service_key).set(age)
                FORECAST_ACTUAL_RPS.labels(service_key).set(values[-1])

                records: list[dict] = []
                interval = self.settings.collection_interval_seconds
                for horizon in horizons_seconds:
                    if horizon < 1 or horizon % interval != 0:
                        raise ValueError(
                            "Forecast horizon must be a positive multiple "
                            "of the collection interval"
                        )
                for forecaster_type in FORECASTERS:
                    predictions_by_step: dict[int, list[float]] = {}
                    maximum_step = max(
                        horizon // interval for horizon in horizons_seconds
                    )
                    predictions_by_step[maximum_step] = forecaster_type().forecast(
                        values,
                        maximum_step,
                    )
                    for horizon in horizons_seconds:
                        steps = horizon // interval
                        prediction = predictions_by_step[maximum_step][steps - 1]
                        target = latest_at + timedelta(seconds=horizon)
                        records.append(
                            {
                                "service_key": service_key,
                                "forecast_generated_at": generated,
                                "target_timestamp": target,
                                "horizon_seconds": horizon,
                                "predicted_rps": prediction,
                                "model_name": forecaster_type.name,
                                "model_version": MODEL_VERSION,
                                "lower_bound": None,
                                "upper_bound": None,
                                "created_at": generated,
                            }
                        )
                        FORECAST_PREDICTED_RPS.labels(
                            service_key,
                            forecaster_type.name,
                            str(horizon),
                        ).set(prediction)
                    FORECAST_MODEL_INFO.labels(
                        service_key,
                        forecaster_type.name,
                        MODEL_VERSION,
                    ).set(1)
                return repository.save_forecasts(records)
        except Exception as error:
            FORECAST_FAILURES.labels(service_key).inc()
            with self.session_factory() as session:
                BreakerRepository(session, self.settings).report_component(
                    service_key,
                    "FORECASTING",
                    healthy=False,
                    reason=f"Forecast generation failed: {type(error).__name__}",
                    failure_threshold=(
                        self.settings.breaker_forecast_failure_threshold
                    ),
                    now=generated,
                )
            raise
        finally:
            FORECAST_GENERATION_SECONDS.labels(service_key).observe(
                time.perf_counter() - started
            )

    def evaluate(self, service_key: str) -> list[ModelAccuracy]:
        if service_key not in self.settings.service_keys:
            raise ValueError("Service is not configured for forecasting")
        with self.session_factory() as session:
            observations = ForecastRepository(session).telemetry_history(
                service_key,
                limit=1000,
            )
        values, _ = self._latest_contiguous_values(
            observations,
            minimum_count=MINIMUM_HISTORY + 1,
            maximum_count=MAX_EVALUATION_SAMPLES,
        )
        interval = self.settings.collection_interval_seconds
        horizons = {
            horizon: horizon // interval
            for horizon in (30, 60)
            if horizon % interval == 0
        }
        if not horizons:
            raise ValueError(
                "Collection interval must divide a 30- or 60-second horizon"
            )
        results = rolling_origin_evaluation(
            values,
            horizons_steps=horizons,
            minimum_history=MINIMUM_HISTORY,
        )
        for result in results:
            labels = (
                service_key,
                result.model_name,
                str(result.horizon_seconds),
            )
            FORECAST_MAE.labels(*labels).set(result.mae)
            if result.wape_percent is not None:
                FORECAST_WAPE.labels(*labels).set(result.wape_percent)
            FORECAST_DEVIATION.labels(*labels).set(result.mae)
        measured_wape = [
            result.wape_percent
            for result in results
            if result.wape_percent is not None
        ]
        if measured_wape:
            with self.session_factory() as session:
                BreakerRepository(session, self.settings).report_component(
                    service_key,
                    "FORECASTING",
                    healthy=(
                        max(measured_wape)
                        <= self.settings.breaker_forecast_wape_max_percent
                    ),
                    reason=(
                        "Forecast WAPE exceeds the configured threshold"
                        if max(measured_wape)
                        > self.settings.breaker_forecast_wape_max_percent
                        else "Forecast accuracy is within the configured threshold"
                    ),
                    failure_threshold=(
                        self.settings.breaker_forecast_failure_threshold
                    ),
                    now=datetime.now(timezone.utc),
                )
        return results

    def _latest_contiguous_values(
        self,
        observations: list[TelemetrySampleRecord],
        *,
        minimum_count: int = MINIMUM_HISTORY,
        maximum_count: int | None = None,
    ) -> tuple[list[float], datetime]:
        interval = self.settings.collection_interval_seconds
        contiguous: list[TelemetrySampleRecord] = []
        expected_earlier: datetime | None = None
        for record in reversed(observations):
            timestamp = _as_utc(record.window_start)
            if (
                record.incoming_rps is None
                or record.data_quality in {"stale", "missing", "invalid"}
                or (
                    expected_earlier is not None
                    and expected_earlier - timestamp
                    != timedelta(seconds=interval)
                )
            ):
                break
            contiguous.append(record)
            expected_earlier = timestamp
            if maximum_count is not None and len(contiguous) >= maximum_count:
                break
        if len(contiguous) < minimum_count:
            raise ValueError(
                "Insufficient contiguous telemetry history; "
                f"need at least {minimum_count} observations"
            )
        chronological = list(reversed(contiguous))
        latest = _as_utc(chronological[-1].window_start)
        return [float(row.incoming_rps) for row in chronological], latest


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def scheduled_forecast_cycle(
    settings: Settings,
    session_factory: sessionmaker,
    *,
    evaluate_accuracy: bool = False,
) -> None:
    service = ForecastService(settings, session_factory)
    for service_key in settings.service_keys:
        try:
            records = service.generate(
                service_key,
                [30, 60],
            )
            logger.info(
                "Generated %d traffic forecasts for service=%s",
                len(records),
                service_key,
            )
            if evaluate_accuracy:
                results = service.evaluate(service_key)
                logger.info(
                    "Evaluated %d forecast model/horizon combinations "
                    "for service=%s",
                    len(results),
                    service_key,
                )
        except Exception as error:
            logger.error(
                "Traffic forecast failed for service=%s error_type=%s",
                service_key,
                type(error).__name__,
            )
