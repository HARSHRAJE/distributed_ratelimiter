import asyncio
from datetime import datetime, timedelta, timezone
from statistics import mean
from typing import Any
from urllib.parse import quote

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.benchmarking.schemas import BenchmarkMetrics, BenchmarkRun
from app.benchmarking.scenario_manager import ScenarioManager
from app.telemetry.models import (
    PolicyExecutionRecord,
    PolicyRecommendationRecord,
    TelemetrySampleRecord,
    TenantSlaAllocationResultRecord,
    TenantSlaAllocationRunRecord,
)


class BenchmarkMetricsCollector:
    def __init__(
        self,
        *,
        prometheus_url: str,
        timeout_seconds: float,
    ) -> None:
        self.prometheus_url = prometheus_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    async def collect(
        self,
        run: BenchmarkRun,
        k6_metrics: BenchmarkMetrics,
        *,
        session: Session,
    ) -> BenchmarkMetrics:
        if run.started_at is None or run.completed_at is None:
            raise ValueError("Benchmark timestamps are required for collection")
        label = run.service_key.replace("\\", "\\\\").replace('"', '\\"')
        app_label = f'application="{label}"'
        gateway_label = 'application="rate-limiter-gateway"'
        expressions = {
            "p50_latency_ms": (
                "1000 * histogram_quantile(0.50, sum by (le) "
                f"(rate(http_server_requests_seconds_bucket{{{app_label}}}[1m])))"
            ),
            "p95_latency_ms": (
                "1000 * histogram_quantile(0.95, sum by (le) "
                f"(rate(http_server_requests_seconds_bucket{{{app_label}}}[1m])))"
            ),
            "p99_latency_ms": (
                "1000 * histogram_quantile(0.99, sum by (le) "
                f"(rate(http_server_requests_seconds_bucket{{{app_label}}}[1m])))"
            ),
            "cpu_usage": f"100 * avg(process_cpu_usage{{{app_label}}})",
            "memory_usage": (
                "100 * sum(jvm_memory_used_bytes"
                f'{{{app_label},area="heap"}}) / '
                f"sum(jvm_memory_max_bytes{{{app_label},area=\"heap\"}} > 0)"
            ),
            "gateway_cpu_usage": (
                f"100 * avg(process_cpu_usage{{{gateway_label}}})"
            ),
            "gateway_memory_usage": (
                "100 * sum(jvm_memory_used_bytes"
                f'{{{gateway_label},area="heap"}}) / '
                f"sum(jvm_memory_max_bytes{{{gateway_label},area=\"heap\"}} > 0)"
            ),
            "redis_latency_ms": (
                "1000 * histogram_quantile(0.95, sum by (le) "
                "(rate(ratelimit_redis_latency_seconds_bucket"
                '{operation="token_bucket"}[1m])))'
            ),
            "redis_commands_per_second": (
                "sum(rate(redis_commands_processed_total[1m]))"
            ),
            "redis_connection_count": "sum(redis_connected_clients)",
            "redis_memory_bytes": "sum(redis_memory_used_bytes)",
            "redis_error_count": (
                "sum(increase(redis_commands_failed_total[1m]))"
            ),
            "forecast_mae": (
                "avg(ai_controller_forecast_mae"
                f'{{service_key="{label}"}})'
            ),
            "forecast_wape": (
                "avg(ai_controller_forecast_wape_percent"
                f'{{service_key="{label}"}})'
            ),
            "recommendation_generation_ms": (
                "1000 * sum(rate(ai_controller_recommendation_generation_seconds_sum"
                f'{{service_key="{label}"}}[1m])) / '
                "sum(rate(ai_controller_recommendation_generation_seconds_count"
                f'{{service_key="{label}"}}[1m]))'
            ),
        }
        values, collection_errors = await self._query_range(
            expressions,
            run.started_at,
            run.completed_at,
        )
        sla_violations, proposal_fairness = self._sla_metrics(run, session)
        stabilization = self._stabilization_metric(run, session)
        (
            policy_changes,
            policy_application_ms,
            propagation_ms,
            oscillation,
        ) = self._policy_metrics(
            run,
            session,
        )
        return k6_metrics.model_copy(
            update={
                "p50_latency_ms": k6_metrics.p50_latency_ms
                if k6_metrics.p50_latency_ms is not None
                else values.get("p50_latency_ms"),
                "p95_latency_ms": k6_metrics.p95_latency_ms
                if k6_metrics.p95_latency_ms is not None
                else values.get("p95_latency_ms"),
                "p99_latency_ms": k6_metrics.p99_latency_ms
                if k6_metrics.p99_latency_ms is not None
                else values.get("p99_latency_ms"),
                "cpu_usage": values.get("cpu_usage"),
                "gateway_cpu_usage": values.get("gateway_cpu_usage"),
                "memory_usage": values.get("memory_usage"),
                "gateway_memory_usage": values.get("gateway_memory_usage"),
                "redis_latency_ms": values.get("redis_latency_ms"),
                "redis_commands_per_second": values.get(
                    "redis_commands_per_second"
                ),
                "redis_connection_count": _as_int(
                    values.get("redis_connection_count")
                ),
                "redis_memory_bytes": _as_int(
                    values.get("redis_memory_bytes")
                ),
                "redis_error_count": _as_int(values.get("redis_error_count")),
                "redis_hot_key_observation": None,
                "sla_violation_count": sla_violations,
                "fairness_index": k6_metrics.fairness_index,
                "fairness_basis": k6_metrics.fairness_basis,
                "tenant_fairness_details": (
                    k6_metrics.tenant_fairness_details
                ),
                "allocation_proposal_fairness_index": proposal_fairness,
                "policy_changes": policy_changes,
                "stabilization_time_seconds": stabilization,
                "policy_application_ms": policy_application_ms,
                "propagation_delay_ms": propagation_ms,
                "forecast_mae": values.get("forecast_mae"),
                "forecast_wape": values.get("forecast_wape"),
                "recommendation_generation_ms": values.get(
                    "recommendation_generation_ms"
                ),
                "oscillation_frequency": oscillation,
                "prometheus_query_reference": (
                    f"{self.prometheus_url}/api/v1/query_range"
                    f"?start={run.started_at.isoformat()}"
                    f"&end={run.completed_at.isoformat()}"
                    f"&service={quote(run.service_key)}"
                ),
                "metrics_collection_errors": [
                    *collection_errors,
                    *k6_metrics.metrics_collection_errors,
                    "redis hot-key behaviour is unavailable without an "
                    "approved key-level Redis instrumentation source",
                ],
            }
        )

    async def _query_range(
        self,
        expressions: dict[str, str],
        start: datetime,
        end: datetime,
    ) -> tuple[dict[str, float | None], list[str]]:
        step = max(1, int((end - start).total_seconds() // 60))
        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            responses = await asyncio.gather(
                *(
                    client.get(
                        f"{self.prometheus_url}/api/v1/query_range",
                        params={
                            "query": expression,
                            "start": start.timestamp(),
                            "end": end.timestamp(),
                            "step": step,
                        },
                    )
                    for expression in expressions.values()
                ),
                return_exceptions=True,
            )
        output: dict[str, float | None] = {}
        errors: list[str] = []
        for name, response in zip(expressions, responses, strict=True):
            if isinstance(response, BaseException):
                output[name] = None
                errors.append(f"{name}: {type(response).__name__}")
                continue
            try:
                response.raise_for_status()
                payload = response.json()
                if payload.get("status") != "success":
                    raise ValueError("non-success status")
                result = payload.get("data", {}).get("result", [])
                samples = [
                    _finite_float(value)
                    for series in result
                    for _, value in series.get("values", [])
                ]
                valid_samples = [
                    value for value in samples if value is not None
                ]
                output[name] = (
                    mean(valid_samples) if valid_samples else None
                )
            except (httpx.HTTPError, ValueError, TypeError) as error:
                output[name] = None
                errors.append(f"{name}: {type(error).__name__}")
        return output, errors

    @staticmethod
    def _sla_metrics(
        run: BenchmarkRun,
        session: Session,
    ) -> tuple[int | None, float | None]:
        latest = session.scalar(
            select(TenantSlaAllocationRunRecord)
            .where(
                TenantSlaAllocationRunRecord.service_key == run.service_key,
                TenantSlaAllocationRunRecord.created_at >= run.started_at,
                TenantSlaAllocationRunRecord.created_at <= run.completed_at,
            )
            .order_by(TenantSlaAllocationRunRecord.created_at.desc())
            .limit(1)
        )
        if latest is None:
            return None, None
        allocations = session.scalars(
            select(TenantSlaAllocationResultRecord).where(
                TenantSlaAllocationResultRecord.allocation_run_id == latest.id
            )
        ).all()
        if not allocations:
            return 0, None
        violations = sum(
            1
            for item in allocations
            if item.allocated_rate < item.guaranteed_rate
            or item.projected_throttle_ratio > item.max_throttle_ratio
            or item.allocated_rate > item.maximum_rate
        )
        demand_ratios = [
            min(1.0, float(item.allocated_rate) / float(item.predicted_demand))
            for item in allocations
            if float(item.predicted_demand) > 0
        ]
        if not demand_ratios:
            return violations, None
        total = sum(demand_ratios)
        squares = sum(value * value for value in demand_ratios)
        fairness = (
            total * total / (len(demand_ratios) * squares)
            if squares
            else 1.0
        )
        return violations, fairness

    @staticmethod
    def _policy_metrics(
        run: BenchmarkRun,
        session: Session,
    ) -> tuple[int, float | None, float | None, float | None]:
        executions = session.scalars(
            select(PolicyExecutionRecord)
            .where(
                PolicyExecutionRecord.service_key == run.service_key,
                PolicyExecutionRecord.started_at >= run.started_at,
                PolicyExecutionRecord.started_at <= run.completed_at,
            )
            .order_by(PolicyExecutionRecord.started_at)
        ).all()
        applied = [
            item
            for item in executions
            if item.effective_config_verified_at is not None
        ]
        application_latencies = [
            (item.policy_submitted_at - item.started_at).total_seconds() * 1000
            for item in applied
            if item.policy_submitted_at is not None
        ]
        propagation_latencies = [
            (
                item.effective_config_verified_at - item.policy_submitted_at
            ).total_seconds() * 1000
            for item in applied
            if item.policy_submitted_at is not None
        ]
        recommendations = session.scalars(
            select(PolicyRecommendationRecord)
            .where(
                PolicyRecommendationRecord.service_key == run.service_key,
                PolicyRecommendationRecord.generated_at >= run.started_at,
                PolicyRecommendationRecord.generated_at <= run.completed_at,
                PolicyRecommendationRecord.action.in_(("INCREASE", "DECREASE")),
            )
            .order_by(PolicyRecommendationRecord.generated_at)
        ).all()
        directions = [item.action for item in recommendations]
        reversals = sum(
            previous != current
            for previous, current in zip(directions, directions[1:])
        )
        duration_hours = max(
            1 / 3600,
            (run.completed_at - run.started_at).total_seconds() / 3600,
        )
        return (
            len(applied),
            (
                mean(application_latencies)
                if application_latencies
                else None
            ),
            (
                mean(propagation_latencies)
                if propagation_latencies
                else None
            ),
            reversals / duration_hours,
        )

    @staticmethod
    def _stabilization_metric(
        run: BenchmarkRun,
        session: Session,
    ) -> float | None:
        if (
            run.scenario.value != "SUDDEN_SPIKE"
            or run.started_at is None
            or run.completed_at is None
        ):
            return None
        start = _as_utc(run.started_at)
        plan = ScenarioManager.build(
            run.scenario,
            duration_seconds=run.duration_seconds,
            start_rps=run.start_rps,
            peak_rps=run.peak_rps,
        )
        baseline_duration = int(plan.stages[0]["duration"])
        baseline_start = start + timedelta(seconds=run.warmup_seconds)
        spike_start = baseline_start + timedelta(seconds=baseline_duration)
        recovery_start = baseline_start + timedelta(
            seconds=plan.recovery_start_seconds or 0
        )
        samples = session.scalars(
            select(TelemetrySampleRecord)
            .where(
                TelemetrySampleRecord.service_key == run.service_key,
                TelemetrySampleRecord.window_start >= baseline_start,
                TelemetrySampleRecord.window_start <= run.completed_at,
                TelemetrySampleRecord.data_quality == "valid",
            )
            .order_by(TelemetrySampleRecord.window_start)
        ).all()
        baseline = [
            item for item in samples
            if _as_utc(item.window_start) < spike_start
            and item.incoming_rps is not None
            and item.incoming_rps > 0
        ]
        if not baseline:
            return None
        expected_rps = mean(float(item.incoming_rps) for item in baseline)
        stable_count = 0
        for item in samples:
            if _as_utc(item.window_start) < recovery_start:
                continue
            if (
                item.incoming_rps is None
                or item.p95_latency_ms is None
                or item.cpu_utilization is None
                or item.incoming_rps < expected_rps * 0.9
                or item.incoming_rps > expected_rps * 1.1
                or float(item.p95_latency_ms)
                    > run.slo_thresholds.max_p95_latency_ms
                or float(item.cpu_utilization)
                    > run.slo_thresholds.max_cpu_usage_percent
            ):
                stable_count = 0
                continue
            rejection_ratio = (
                float(item.rejected_rps or 0) / float(item.incoming_rps)
            )
            error_ratio = (
                float(item.error_rate or 0)
                / max(float(item.allowed_rps or 0), 0.001)
            )
            if (
                rejection_ratio > run.slo_thresholds.max_rejection_ratio
                or error_ratio > run.slo_thresholds.max_backend_error_ratio
            ):
                stable_count = 0
                continue
            stable_count += 1
            if stable_count == 2:
                return max(
                    0.0,
                    (_as_utc(item.window_start) - recovery_start).total_seconds(),
                )
        return None


def _finite_float(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return parsed if parsed == parsed and abs(parsed) != float("inf") else None


def _as_int(value: float | None) -> int | None:
    return int(value) if value is not None else None


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
