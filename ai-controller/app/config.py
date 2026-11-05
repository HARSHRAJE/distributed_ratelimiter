import os
import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    prometheus_url: str
    service_keys: tuple[str, ...]
    collection_interval_seconds: int
    stale_after_seconds: int
    aggregation_window_seconds: int
    prometheus_timeout_seconds: float
    api_key: str
    db_host: str
    db_port: int
    db_name: str
    db_username: str
    db_password: str

    @classmethod
    def from_env(cls) -> "Settings":
        service_keys = tuple(
            key.strip()
            for key in os.getenv(
                "AI_CONTROLLER_SERVICE_KEYS",
                "orders-service",
            ).split(",")
            if key.strip()
        )
        if not service_keys:
            raise ValueError("AI_CONTROLLER_SERVICE_KEYS cannot be empty")
        if any(
            re.fullmatch(r"[A-Za-z0-9._-]{1,100}", key) is None
            for key in service_keys
        ):
            raise ValueError(
                "AI_CONTROLLER_SERVICE_KEYS contains an invalid service key"
            )
        if len(set(service_keys)) != len(service_keys):
            raise ValueError("AI_CONTROLLER_SERVICE_KEYS contains duplicates")

        interval = int(
            os.getenv("AI_CONTROLLER_COLLECTION_INTERVAL_SECONDS", "15")
        )
        aggregation_window = int(
            os.getenv("AI_CONTROLLER_AGGREGATION_WINDOW_SECONDS", "300")
        )
        if interval < 1:
            raise ValueError(
                "AI_CONTROLLER_COLLECTION_INTERVAL_SECONDS must be positive"
            )
        if aggregation_window < interval:
            raise ValueError(
                "AI_CONTROLLER_AGGREGATION_WINDOW_SECONDS must be at least "
                "the collection interval"
            )
        stale_after = int(
            os.getenv("AI_CONTROLLER_STALE_AFTER_SECONDS", "60")
        )
        if stale_after < 1:
            raise ValueError(
                "AI_CONTROLLER_STALE_AFTER_SECONDS must be positive"
            )
        timeout = float(
            os.getenv("AI_CONTROLLER_PROMETHEUS_TIMEOUT_SECONDS", "5")
        )
        if timeout <= 0:
            raise ValueError(
                "AI_CONTROLLER_PROMETHEUS_TIMEOUT_SECONDS must be positive"
            )

        return cls(
            prometheus_url=os.getenv(
                "AI_CONTROLLER_PROMETHEUS_URL",
                "http://localhost:9090",
            ).rstrip("/"),
            service_keys=service_keys,
            collection_interval_seconds=interval,
            stale_after_seconds=stale_after,
            aggregation_window_seconds=aggregation_window,
            prometheus_timeout_seconds=timeout,
            api_key=os.getenv("AI_CONTROLLER_API_KEY", ""),
            db_host=os.getenv("DB_HOST", "localhost"),
            db_port=int(os.getenv("DB_PORT", "5432")),
            db_name=os.getenv("DB_NAME", "rate_limiter"),
            db_username=os.getenv("DB_USERNAME", "rate_limiter_app"),
            db_password=os.getenv("DB_PASSWORD", ""),
        )
