import os
import re
from dataclasses import dataclass


def _boolean_from_env(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in {"true", "1", "yes"}:
        return True
    if normalized in {"false", "0", "no"}:
        return False
    raise ValueError(f"{name} must be a boolean value")


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
    max_change_percent: float = 10.0
    cooldown_seconds: int = 300
    minimum_forecast_confidence: float = 0.7
    maximum_telemetry_age_seconds: int = 60
    maximum_cpu_utilization: float = 85.0
    maximum_p95_latency_ms: float = 500.0
    maximum_p99_latency_ms: float = 1000.0
    maximum_5xx_rate: float = 5.0
    maximum_queue_depth: float = 100.0
    recommendation_ttl_seconds: int = 300
    execution_enabled: bool = False
    emergency_kill_switch: bool = True
    execution_enabled_services: tuple[str, ...] = ()
    execution_max_change_percent: float = 5.0
    execution_cooldown_seconds: int = 300
    execution_max_changes_per_hour: int = 3
    execution_rollout_duration_hours: int = 24
    execution_minimum_rate_rps: float = 1.0
    execution_maximum_shadow_age_seconds: int = 900
    execution_maximum_shadow_forecast_error_percent: float = 50.0
    gateway_policy_cache_ttl_seconds: float = 1.0
    policy_service_url: str = "http://localhost:8081"
    policy_service_api_key: str = ""
    administrator_api_key: str = ""
    policy_service_timeout_seconds: float = 3.0
    rollback_p95_threshold_ms: float = 500.0
    rollback_p95_consecutive_windows: int = 3
    rollback_5xx_threshold_percent: float = 5.0
    rollback_5xx_consecutive_windows: int = 2
    rollback_critical_5xx_percent: float = 20.0
    rollback_cpu_threshold_percent: float = 90.0
    rollback_cpu_consecutive_windows: int = 3
    rollback_queue_depth_threshold: float = 100.0
    rollback_queue_growth_windows: int = 3
    rollback_throughput_drop_percent: float = 30.0
    rollback_throughput_consecutive_windows: int = 3
    rollback_observation_period_seconds: int = 60
    rollback_redis_sync_timeout_seconds: int = 60
    rollback_cooldown_seconds: int = 3600
    rollback_max_attempts_per_hour: int = 2
    rollback_minimum_healthy_windows: int = 5
    rollback_telemetry_max_age_seconds: int = 60
    breaker_failure_threshold: int = 3
    breaker_recovery_timeout_seconds: int = 300
    breaker_half_open_max_calls: int = 1
    breaker_success_threshold: int = 1
    breaker_recovery_max_change_percent: float = 2.0
    breaker_telemetry_max_age_seconds: int = 60
    breaker_forecast_failure_threshold: int = 3
    breaker_forecast_wape_max_percent: float = 50.0
    breaker_policy_failure_threshold: int = 3
    breaker_redis_failure_threshold: int = 3
    breaker_execution_failure_threshold: int = 3
    breaker_rollback_limit: int = 2
    breaker_rollback_window_seconds: int = 1800
    benchmark_target_url: str = ""
    benchmark_k6_binary: str = "k6"
    benchmark_worker_poll_seconds: int = 2
    benchmark_max_duration_seconds: int = 3600
    benchmark_max_rps: int = 100
    benchmark_allowed_hosts: tuple[str, ...] = (
        "localhost:8080",
        "host.docker.internal:8080",
        "gateway:8080",
    )
    benchmark_route_paths: tuple[str, ...] = ("/",)
    benchmark_tenant_tokens: tuple[str, ...] = ()
    benchmark_git_commit: str = "UNSPECIFIED"

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

        settings = cls(
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
            max_change_percent=float(
                os.getenv("AI_CONTROLLER_MAX_CHANGE_PERCENT", "10")
            ),
            cooldown_seconds=int(
                os.getenv("AI_CONTROLLER_RECOMMENDATION_COOLDOWN_SECONDS", "300")
            ),
            minimum_forecast_confidence=float(
                os.getenv("AI_CONTROLLER_MINIMUM_FORECAST_CONFIDENCE", "0.7")
            ),
            maximum_telemetry_age_seconds=int(
                os.getenv("AI_CONTROLLER_MAXIMUM_TELEMETRY_AGE_SECONDS", "60")
            ),
            maximum_cpu_utilization=float(
                os.getenv("AI_CONTROLLER_MAXIMUM_CPU_UTILIZATION", "85")
            ),
            maximum_p95_latency_ms=float(
                os.getenv("AI_CONTROLLER_MAXIMUM_P95_LATENCY_MS", "500")
            ),
            maximum_p99_latency_ms=float(
                os.getenv("AI_CONTROLLER_MAXIMUM_P99_LATENCY_MS", "1000")
            ),
            maximum_5xx_rate=float(
                os.getenv("AI_CONTROLLER_MAXIMUM_5XX_RATE", "5")
            ),
            maximum_queue_depth=float(
                os.getenv("AI_CONTROLLER_MAXIMUM_QUEUE_DEPTH", "100")
            ),
            recommendation_ttl_seconds=int(
                os.getenv("AI_CONTROLLER_RECOMMENDATION_TTL_SECONDS", "300")
            ),
            execution_enabled=_boolean_from_env(
                "AI_CONTROLLER_EXECUTION_ENABLED",
                False,
            ),
            emergency_kill_switch=_boolean_from_env(
                "AI_CONTROLLER_EMERGENCY_KILL_SWITCH",
                True,
            ),
            execution_enabled_services=tuple(
                key.strip()
                for key in os.getenv(
                    "AI_CONTROLLER_EXECUTION_ENABLED_SERVICES", ""
                ).split(",")
                if key.strip()
            ),
            execution_max_change_percent=float(
                os.getenv(
                    "AI_CONTROLLER_EXECUTION_MAX_CHANGE_PERCENT", "5"
                )
            ),
            execution_cooldown_seconds=int(
                os.getenv("AI_CONTROLLER_EXECUTION_COOLDOWN_SECONDS", "300")
            ),
            execution_max_changes_per_hour=int(
                os.getenv(
                    "AI_CONTROLLER_EXECUTION_MAX_CHANGES_PER_HOUR", "3"
                )
            ),
            execution_rollout_duration_hours=int(
                os.getenv(
                    "AI_CONTROLLER_EXECUTION_ROLLOUT_DURATION_HOURS", "24"
                )
            ),
            execution_minimum_rate_rps=float(
                os.getenv("AI_CONTROLLER_EXECUTION_MINIMUM_RATE_RPS", "1")
            ),
            execution_maximum_shadow_age_seconds=int(
                os.getenv(
                    "AI_CONTROLLER_EXECUTION_MAXIMUM_SHADOW_AGE_SECONDS",
                    "900",
                )
            ),
            execution_maximum_shadow_forecast_error_percent=float(
                os.getenv(
                    "AI_CONTROLLER_EXECUTION_MAXIMUM_SHADOW_FORECAST_ERROR_PERCENT",
                    "50",
                )
            ),
            gateway_policy_cache_ttl_seconds=float(
                os.getenv(
                    "AI_CONTROLLER_GATEWAY_POLICY_CACHE_TTL_SECONDS", "1"
                )
            ),
            policy_service_url=os.getenv(
                "AI_CONTROLLER_POLICY_SERVICE_URL",
                "http://localhost:8081",
            ).rstrip("/"),
            policy_service_api_key=os.getenv(
                "AI_CONTROLLER_POLICY_SERVICE_API_KEY", ""
            ),
            administrator_api_key=os.getenv(
                "AI_CONTROLLER_ADMIN_API_KEY", ""
            ),
            policy_service_timeout_seconds=float(
                os.getenv(
                    "AI_CONTROLLER_POLICY_SERVICE_TIMEOUT_SECONDS", "3"
                )
            ),
            rollback_p95_threshold_ms=float(
                os.getenv("AI_CONTROLLER_ROLLBACK_P95_THRESHOLD_MS", "500")
            ),
            rollback_p95_consecutive_windows=int(
                os.getenv(
                    "AI_CONTROLLER_ROLLBACK_P95_CONSECUTIVE_WINDOWS", "3"
                )
            ),
            rollback_5xx_threshold_percent=float(
                os.getenv(
                    "AI_CONTROLLER_ROLLBACK_5XX_THRESHOLD_PERCENT", "5"
                )
            ),
            rollback_5xx_consecutive_windows=int(
                os.getenv(
                    "AI_CONTROLLER_ROLLBACK_5XX_CONSECUTIVE_WINDOWS", "2"
                )
            ),
            rollback_critical_5xx_percent=float(
                os.getenv(
                    "AI_CONTROLLER_ROLLBACK_CRITICAL_5XX_PERCENT", "20"
                )
            ),
            rollback_cpu_threshold_percent=float(
                os.getenv("AI_CONTROLLER_ROLLBACK_CPU_THRESHOLD_PERCENT", "90")
            ),
            rollback_cpu_consecutive_windows=int(
                os.getenv(
                    "AI_CONTROLLER_ROLLBACK_CPU_CONSECUTIVE_WINDOWS", "3"
                )
            ),
            rollback_queue_depth_threshold=float(
                os.getenv(
                    "AI_CONTROLLER_ROLLBACK_QUEUE_DEPTH_THRESHOLD", "100"
                )
            ),
            rollback_queue_growth_windows=int(
                os.getenv("AI_CONTROLLER_ROLLBACK_QUEUE_GROWTH_WINDOWS", "3")
            ),
            rollback_throughput_drop_percent=float(
                os.getenv(
                    "AI_CONTROLLER_ROLLBACK_THROUGHPUT_DROP_PERCENT", "30"
                )
            ),
            rollback_throughput_consecutive_windows=int(
                os.getenv(
                    "AI_CONTROLLER_ROLLBACK_THROUGHPUT_CONSECUTIVE_WINDOWS",
                    "3",
                )
            ),
            rollback_observation_period_seconds=int(
                os.getenv(
                    "AI_CONTROLLER_ROLLBACK_OBSERVATION_PERIOD_SECONDS", "60"
                )
            ),
            rollback_redis_sync_timeout_seconds=int(
                os.getenv(
                    "AI_CONTROLLER_ROLLBACK_REDIS_SYNC_TIMEOUT_SECONDS", "60"
                )
            ),
            rollback_cooldown_seconds=int(
                os.getenv("AI_CONTROLLER_ROLLBACK_COOLDOWN_SECONDS", "3600")
            ),
            rollback_max_attempts_per_hour=int(
                os.getenv(
                    "AI_CONTROLLER_ROLLBACK_MAX_ATTEMPTS_PER_HOUR", "2"
                )
            ),
            rollback_minimum_healthy_windows=int(
                os.getenv(
                    "AI_CONTROLLER_ROLLBACK_MINIMUM_HEALTHY_WINDOWS", "5"
                )
            ),
            rollback_telemetry_max_age_seconds=int(
                os.getenv(
                    "AI_CONTROLLER_ROLLBACK_TELEMETRY_MAX_AGE_SECONDS", "60"
                )
            ),
            breaker_failure_threshold=int(
                os.getenv("AI_CONTROLLER_BREAKER_FAILURE_THRESHOLD", "3")
            ),
            breaker_recovery_timeout_seconds=int(
                os.getenv(
                    "AI_CONTROLLER_BREAKER_RECOVERY_TIMEOUT_SECONDS",
                    "300",
                )
            ),
            breaker_half_open_max_calls=int(
                os.getenv("AI_CONTROLLER_BREAKER_HALF_OPEN_MAX_CALLS", "1")
            ),
            breaker_success_threshold=int(
                os.getenv("AI_CONTROLLER_BREAKER_SUCCESS_THRESHOLD", "1")
            ),
            breaker_recovery_max_change_percent=float(
                os.getenv(
                    "AI_CONTROLLER_BREAKER_RECOVERY_MAX_CHANGE_PERCENT",
                    "2",
                )
            ),
            breaker_telemetry_max_age_seconds=int(
                os.getenv(
                    "AI_CONTROLLER_BREAKER_TELEMETRY_MAX_AGE_SECONDS",
                    "60",
                )
            ),
            breaker_forecast_failure_threshold=int(
                os.getenv(
                    "AI_CONTROLLER_BREAKER_FORECAST_FAILURE_THRESHOLD",
                    "3",
                )
            ),
            breaker_forecast_wape_max_percent=float(
                os.getenv(
                    "AI_CONTROLLER_BREAKER_FORECAST_WAPE_MAX_PERCENT",
                    "50",
                )
            ),
            breaker_policy_failure_threshold=int(
                os.getenv(
                    "AI_CONTROLLER_BREAKER_POLICY_FAILURE_THRESHOLD",
                    "3",
                )
            ),
            breaker_redis_failure_threshold=int(
                os.getenv(
                    "AI_CONTROLLER_BREAKER_REDIS_FAILURE_THRESHOLD",
                    "3",
                )
            ),
            breaker_execution_failure_threshold=int(
                os.getenv(
                    "AI_CONTROLLER_BREAKER_EXECUTION_FAILURE_THRESHOLD",
                    "3",
                )
            ),
            breaker_rollback_limit=int(
                os.getenv("AI_CONTROLLER_BREAKER_ROLLBACK_LIMIT", "2")
            ),
            breaker_rollback_window_seconds=int(
                os.getenv(
                    "AI_CONTROLLER_BREAKER_ROLLBACK_WINDOW_SECONDS",
                    "1800",
                )
            ),
            benchmark_target_url=os.getenv(
                "AI_CONTROLLER_BENCHMARK_TARGET_URL",
                "",
            ).rstrip("/"),
            benchmark_k6_binary=os.getenv(
                "AI_CONTROLLER_BENCHMARK_K6_BINARY",
                "k6",
            ),
            benchmark_worker_poll_seconds=int(
                os.getenv("AI_CONTROLLER_BENCHMARK_WORKER_POLL_SECONDS", "2")
            ),
            benchmark_max_duration_seconds=int(
                os.getenv(
                    "AI_CONTROLLER_BENCHMARK_MAX_DURATION_SECONDS",
                    "3600",
                )
            ),
            benchmark_max_rps=int(
                os.getenv("AI_CONTROLLER_BENCHMARK_MAX_RPS", "100")
            ),
            benchmark_allowed_hosts=tuple(
                host.strip().lower()
                for host in os.getenv(
                    "AI_CONTROLLER_BENCHMARK_ALLOWED_HOSTS",
                    "localhost:8080,host.docker.internal:8080,gateway:8080",
                ).split(",")
                if host.strip()
            ),
            benchmark_route_paths=tuple(
                path.strip()
                for path in os.getenv(
                    "AI_CONTROLLER_BENCHMARK_ROUTE_PATHS",
                    "/",
                ).split(",")
                if path.strip()
            ),
            benchmark_tenant_tokens=tuple(
                token.strip()
                for token in os.getenv(
                    "AI_CONTROLLER_BENCHMARK_TENANT_TOKENS",
                    "",
                ).split(",")
                if token.strip()
            ),
            benchmark_git_commit=os.getenv(
                "AI_CONTROLLER_GIT_COMMIT",
                "UNSPECIFIED",
            )[:80],
        )
        if not 0 < settings.max_change_percent <= 100:
            raise ValueError("AI_CONTROLLER_MAX_CHANGE_PERCENT must be in (0, 100]")
        if settings.cooldown_seconds < 0:
            raise ValueError(
                "AI_CONTROLLER_RECOMMENDATION_COOLDOWN_SECONDS cannot be negative"
            )
        if not 0 <= settings.minimum_forecast_confidence <= 1:
            raise ValueError(
                "AI_CONTROLLER_MINIMUM_FORECAST_CONFIDENCE must be between 0 and 1"
            )
        if settings.maximum_telemetry_age_seconds < 1:
            raise ValueError(
                "AI_CONTROLLER_MAXIMUM_TELEMETRY_AGE_SECONDS must be positive"
            )
        if not 0 < settings.maximum_cpu_utilization <= 100:
            raise ValueError(
                "AI_CONTROLLER_MAXIMUM_CPU_UTILIZATION must be in (0, 100]"
            )
        if any(
            value <= 0
            for value in (
                settings.maximum_p95_latency_ms,
                settings.maximum_p99_latency_ms,
                settings.recommendation_ttl_seconds,
            )
        ) or min(settings.maximum_5xx_rate, settings.maximum_queue_depth) < 0:
            raise ValueError(
                "Latency and TTL thresholds must be positive; 5xx and queue "
                "thresholds must be non-negative"
            )
        if not 0 < settings.execution_max_change_percent <= 100:
            raise ValueError(
                "AI_CONTROLLER_EXECUTION_MAX_CHANGE_PERCENT must be in (0, 100]"
            )
        if (
            settings.execution_cooldown_seconds < 300
            or settings.execution_max_changes_per_hour < 1
            or settings.execution_rollout_duration_hours < 1
            or settings.execution_minimum_rate_rps <= 0
            or settings.execution_maximum_shadow_age_seconds < 1
            or settings.execution_maximum_shadow_forecast_error_percent < 0
            or settings.gateway_policy_cache_ttl_seconds <= 0
            or settings.policy_service_timeout_seconds <= 0
        ):
            raise ValueError("Invalid execution or rollout safety setting")
        if len(settings.execution_enabled_services) > 1:
            raise ValueError(
                "AI_CONTROLLER_EXECUTION_ENABLED_SERVICES supports at most "
                "one initial rollout service"
            )
        if any(
            re.fullmatch(r"[A-Za-z0-9._-]{1,100}", key) is None
            for key in settings.execution_enabled_services
        ):
            raise ValueError(
                "AI_CONTROLLER_EXECUTION_ENABLED_SERVICES contains an invalid key"
            )
        if settings.execution_enabled and (
            len(settings.execution_enabled_services) != 1
            or len(settings.policy_service_api_key) < 32
            or len(settings.administrator_api_key) < 32
        ):
            raise ValueError(
                "Enabled execution requires exactly one rollout service and "
                "32-character Policy Service and administrator API keys"
            )
        if (
            settings.rollback_p95_threshold_ms <= 0
            or settings.rollback_5xx_threshold_percent <= 0
            or settings.rollback_5xx_threshold_percent > 100
            or settings.rollback_critical_5xx_percent
                <= settings.rollback_5xx_threshold_percent
            or settings.rollback_critical_5xx_percent > 100
            or not 0 < settings.rollback_cpu_threshold_percent <= 100
            or settings.rollback_queue_depth_threshold < 0
            or not 0 < settings.rollback_throughput_drop_percent <= 100
            or min(
                settings.rollback_p95_consecutive_windows,
                settings.rollback_5xx_consecutive_windows,
                settings.rollback_cpu_consecutive_windows,
                settings.rollback_queue_growth_windows,
                settings.rollback_throughput_consecutive_windows,
                settings.rollback_observation_period_seconds,
                settings.rollback_redis_sync_timeout_seconds,
                settings.rollback_cooldown_seconds,
                settings.rollback_max_attempts_per_hour,
                settings.rollback_minimum_healthy_windows,
                settings.rollback_telemetry_max_age_seconds,
            ) < 1
        ):
            raise ValueError("Invalid rollback threshold or safety setting")
        if (
            min(
                settings.breaker_failure_threshold,
                settings.breaker_recovery_timeout_seconds,
                settings.breaker_half_open_max_calls,
                settings.breaker_success_threshold,
                settings.breaker_telemetry_max_age_seconds,
                settings.breaker_forecast_failure_threshold,
                settings.breaker_policy_failure_threshold,
                settings.breaker_redis_failure_threshold,
                settings.breaker_execution_failure_threshold,
                settings.breaker_rollback_limit,
                settings.breaker_rollback_window_seconds,
            ) < 1
            or not 0 < settings.breaker_recovery_max_change_percent <= 100
            or settings.breaker_forecast_wape_max_percent < 0
            or settings.breaker_success_threshold
            > settings.breaker_half_open_max_calls
        ):
            raise ValueError("Invalid circuit breaker setting")
        if (
            settings.benchmark_worker_poll_seconds < 1
            or settings.benchmark_max_duration_seconds < 1
            or not 1 <= settings.benchmark_max_rps <= 1000
            or not settings.benchmark_k6_binary
            or not settings.benchmark_allowed_hosts
            or not settings.benchmark_route_paths
            or any(
                not path.startswith("/")
                for path in settings.benchmark_route_paths
            )
        ):
            raise ValueError("Invalid benchmark worker setting")
        return settings
