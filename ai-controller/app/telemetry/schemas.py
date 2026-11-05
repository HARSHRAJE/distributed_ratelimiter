from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

DataQuality = Literal["valid", "partial", "stale", "missing", "invalid"]


class TelemetrySample(BaseModel):
    id: UUID
    service_key: str = Field(max_length=100)
    timestamp: datetime = Field(validation_alias="window_start")
    window_seconds: int = Field(gt=0)
    incoming_rps: float | None = Field(default=None, ge=0)
    allowed_rps: float | None = Field(default=None, ge=0)
    rejected_rps: float | None = Field(default=None, ge=0)
    p95_latency_ms: float | None = Field(default=None, ge=0)
    p99_latency_ms: float | None = Field(default=None, ge=0)
    error_rate: float | None = Field(default=None, ge=0)
    cpu_utilization: float | None = Field(default=None, ge=0)
    memory_utilization: float | None = Field(default=None, ge=0)
    redis_latency_ms: float | None = Field(default=None, ge=0)
    queue_depth: float | None = Field(default=None, ge=0)
    data_quality: DataQuality
    collected_at: datetime

    model_config = ConfigDict(from_attributes=True)


class TelemetryHistory(BaseModel):
    service_key: str
    samples: list[TelemetrySample]


class ServiceCollectionStatus(BaseModel):
    service_key: str
    state: Literal["idle", "success", "failed", "stale"]
    last_attempt_at: datetime | None
    last_success_at: datetime | None
    last_quality: DataQuality | None
    last_error: str | None
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class CollectionStatus(BaseModel):
    collection_interval_seconds: int
    services: list[ServiceCollectionStatus]


class TelemetryWindow(BaseModel):
    service_key: str
    window_start: datetime
    window_seconds: int
    mean_incoming_rps: float | None
    max_incoming_rps: float | None
    mean_allowed_rps: float | None
    mean_rejected_rps: float | None
    mean_p95_latency_ms: float | None
    max_p95_latency_ms: float | None
    mean_p99_latency_ms: float | None
    max_p99_latency_ms: float | None
    mean_error_rate: float | None
    missing_sample_count: int

    model_config = ConfigDict(from_attributes=True)
