from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from app.api.telemetry import get_session, require_internal_api_key
from app.forecasting.forecast_service import ForecastService
from app.forecasting.schemas import (
    ForecastAccuracy,
    ForecastRequest,
    ForecastResults,
    TrafficForecast,
)
from app.storage.repositories import ForecastRepository

router = APIRouter(
    prefix="/api/v1/forecast",
    tags=["forecast"],
    dependencies=[Depends(require_internal_api_key)],
)


def _forecast_service(request: Request) -> ForecastService:
    return ForecastService(
        request.app.state.settings,
        request.app.state.session_factory,
    )


def _check_service_key(request: Request, service_key: str) -> None:
    if service_key not in request.app.state.settings.service_keys:
        raise HTTPException(status_code=404, detail="Service not found")


@router.post("/{service_key}", response_model=ForecastResults)
def create_forecast(
    service_key: str,
    request: Request,
    payload: ForecastRequest | None = None,
) -> ForecastResults:
    _check_service_key(request, service_key)
    forecast_request = payload or ForecastRequest()
    try:
        records = _forecast_service(request).generate(
            service_key,
            forecast_request.horizons_seconds,
        )
    except ValueError as error:
        message = str(error).lower()
        status_code = 409 if "history" in message or "stale" in message else 422
        raise HTTPException(status_code=status_code, detail=str(error)) from error
    return ForecastResults(
        service_key=service_key,
        forecasts=[TrafficForecast.model_validate(record) for record in records],
    )


@router.get("/latest/{service_key}", response_model=ForecastResults)
def latest_forecast(
    service_key: str,
    request: Request,
    session: Session = Depends(get_session),
) -> ForecastResults:
    _check_service_key(request, service_key)
    records = ForecastRepository(session).latest_forecasts(service_key)
    if not records:
        raise HTTPException(status_code=404, detail="Forecast not found")
    return ForecastResults(
        service_key=service_key,
        forecasts=[TrafficForecast.model_validate(record) for record in records],
    )


@router.get("/history/{service_key}", response_model=ForecastResults)
def forecast_history(
    service_key: str,
    request: Request,
    limit: int = Query(default=100, ge=1, le=1000),
    session: Session = Depends(get_session),
) -> ForecastResults:
    _check_service_key(request, service_key)
    records = ForecastRepository(session).forecast_history(
        service_key,
        limit=limit,
    )
    return ForecastResults(
        service_key=service_key,
        forecasts=[TrafficForecast.model_validate(record) for record in records],
    )


@router.get("/accuracy/{service_key}", response_model=ForecastAccuracy)
def forecast_accuracy(
    service_key: str,
    request: Request,
) -> ForecastAccuracy:
    _check_service_key(request, service_key)
    try:
        results = _forecast_service(request).evaluate(service_key)
    except ValueError as error:
        status_code = 409 if "history" in str(error).lower() else 422
        raise HTTPException(status_code=status_code, detail=str(error)) from error
    return ForecastAccuracy(
        service_key=service_key,
        evaluation_method="rolling_origin",
        models=results,
    )
