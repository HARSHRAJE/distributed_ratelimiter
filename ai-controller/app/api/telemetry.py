import hmac
from datetime import datetime, timedelta, timezone
from collections.abc import Iterator

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from sqlalchemy.orm import Session

from app.config import Settings
from app.storage.repositories import TelemetryRepository
from app.telemetry.schemas import (
    CollectionStatus,
    ServiceCollectionStatus,
    TelemetryHistory,
    TelemetrySample,
)

def require_internal_api_key(
    request: Request,
    supplied_key: str | None = Header(
        default=None,
        alias="X-Internal-API-Key",
    ),
) -> None:
    settings: Settings = request.app.state.settings
    expected_key = settings.api_key
    if len(expected_key) < 32:
        raise HTTPException(
            status_code=503,
            detail="Internal telemetry API authentication is not configured",
        )
    if supplied_key is None or not hmac.compare_digest(
        supplied_key,
        expected_key,
    ):
        raise HTTPException(status_code=401, detail="Unauthorized")


router = APIRouter(
    prefix="/api/v1/telemetry",
    tags=["telemetry"],
    dependencies=[Depends(require_internal_api_key)],
)


def get_session(request: Request) -> Iterator[Session]:
    session_factory = request.app.state.session_factory
    with session_factory() as session:
        yield session


@router.get("/latest/{service_key}", response_model=TelemetrySample)
def latest(
    service_key: str,
    session: Session = Depends(get_session),
) -> TelemetrySample:
    record = TelemetryRepository(session).latest(service_key)
    if record is None:
        raise HTTPException(status_code=404, detail="Telemetry sample not found")
    return TelemetrySample.model_validate(record)


@router.get("/history/{service_key}", response_model=TelemetryHistory)
def history(
    service_key: str,
    limit: int = Query(default=100, ge=1, le=1000),
    before: datetime | None = None,
    session: Session = Depends(get_session),
) -> TelemetryHistory:
    records = TelemetryRepository(session).history(
        service_key,
        limit=limit,
        before=before,
    )
    return TelemetryHistory(
        service_key=service_key,
        samples=[
            TelemetrySample.model_validate(record)
            for record in records
        ],
    )


@router.get("/status", response_model=CollectionStatus)
def status(
    request: Request,
    session: Session = Depends(get_session),
) -> CollectionStatus:
    settings: Settings = request.app.state.settings
    records = {
        record.service_key: record
        for record in TelemetryRepository(session).collection_status()
    }
    now = datetime.now(timezone.utc)
    stale_after = max(
        settings.stale_after_seconds,
        settings.collection_interval_seconds * 3,
    )
    services = []
    for service_key in settings.service_keys:
        record = records.get(service_key)
        if record is None:
            services.append(
                ServiceCollectionStatus(
                    service_key=service_key,
                    state="idle",
                    last_attempt_at=None,
                    last_success_at=None,
                    last_quality=None,
                    last_error=None,
                    updated_at=now,
                )
            )
            continue

        state = record.state
        updated_at = record.updated_at
        if updated_at.tzinfo is None:
            updated_at = updated_at.replace(tzinfo=timezone.utc)
        if (
            state == "success"
            and now - updated_at > timedelta(seconds=stale_after)
        ):
            state = "stale"
        services.append(
            ServiceCollectionStatus(
                service_key=record.service_key,
                state=state,
                last_attempt_at=record.last_attempt_at,
                last_success_at=record.last_success_at,
                last_quality=record.last_quality,
                last_error=record.last_error,
                updated_at=record.updated_at,
            )
        )
    return CollectionStatus(
        collection_interval_seconds=settings.collection_interval_seconds,
        services=services,
    )
