from datetime import datetime, timedelta, timezone
import math
from uuid import uuid4

from app.config import Settings
from app.recommendations.schemas import RecommendationRecordSchema
from app.safety.schemas import ValidationStatus
from app.shadow.outcome_calculator import calculate_outcome
from app.shadow.schemas import (
    ShadowComparison,
    ShadowEvaluationRequest,
    ShadowEvaluationResult,
    StrategyComparison,
    StrategyName,
    TrafficPoint,
)
from app.shadow.shadow_repository import ShadowRepository
from app.shadow.traffic_simulator import TokenBucket, simulate_token_buckets
from app.telemetry.models import ShadowEvaluationRecord, TelemetrySampleRecord


class ShadowEvaluationError(ValueError):
    pass


class ShadowService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def evaluate(
        self,
        service_key: str,
        request: ShadowEvaluationRequest,
        repository: ShadowRepository,
        *,
        now: datetime | None = None,
    ) -> ShadowEvaluationResult:
        evaluated_at = _as_utc(now or datetime.now(timezone.utc))
        recommendation = repository.recommendation(request.recommendation_id)
        if recommendation is None or recommendation.service_key != service_key:
            raise ShadowEvaluationError("Recommendation not found for service")
        if recommendation.scope != "GLOBAL":
            raise ShadowEvaluationError(
                "Only global service recommendations can be evaluated"
            )
        policy = repository.policy_snapshot(
            service_key,
            tenant_key=request.tenant_key,
            route_key=request.route_key,
        )
        if policy is None:
            raise ShadowEvaluationError(
                "Active service, tenant, and route policy snapshot not found"
            )
        if recommendation.status not in {"PENDING", "ACCEPTED"}:
            raise ShadowEvaluationError(
                "Recommendation is not eligible for shadow evaluation"
            )
        if not policy.adaptive_control_enabled:
            raise ShadowEvaluationError(
                "Service is not enabled for adaptive control"
            )
        if _as_utc(recommendation.expires_at) <= evaluated_at:
            raise ShadowEvaluationError("Recommendation has expired")
        if recommendation.policy_version != policy.current_policy_version:
            raise ShadowEvaluationError(
                "Recommendation is based on an outdated policy version"
            )
        if not math.isclose(
            float(recommendation.current_rate),
            policy.current_rate,
            rel_tol=0,
            abs_tol=0.0005,
        ):
            raise ShadowEvaluationError(
                "Current rate does not match the recommendation policy snapshot"
            )
        if not policy.min_refill_rate <= policy.current_rate <= (
            policy.hard_max_refill_rate
        ):
            raise ShadowEvaluationError(
                "Current rate is outside configured service safety bounds"
            )
        if recommendation.recommended_rate > min(
            recommendation.safe_capacity_rps,
            request.safe_capacity_rps,
            policy.hard_max_refill_rate,
        ):
            raise ShadowEvaluationError(
                "Proposed rate exceeds safe capacity or service hard maximum"
            )
        minimum_recommendation_rate = max(
            policy.min_refill_rate,
            policy.current_rate
            * (1 - self.settings.max_change_percent / 100),
        )
        maximum_recommendation_rate = min(
            request.safe_capacity_rps,
            policy.hard_max_refill_rate,
            policy.current_rate
            * (1 + self.settings.max_change_percent / 100),
        )
        if not minimum_recommendation_rate <= recommendation.recommended_rate <= (
            maximum_recommendation_rate
        ):
            raise ShadowEvaluationError(
                "Forecast-assisted rate violates current safety constraints"
            )
        if not minimum_recommendation_rate <= request.rule_based_rate <= min(
            request.safe_capacity_rps,
            policy.hard_max_refill_rate,
            policy.current_rate
            * (1 + self.settings.max_change_percent / 100),
        ):
            raise ShadowEvaluationError(
                "Rule-based rate is outside configured service safety bounds"
            )

        validation = repository.latest_validation(recommendation.id)
        if validation is None or validation.status != ValidationStatus.VALID.value:
            raise ShadowEvaluationError(
                "Recommendation does not have a passing safety validation"
            )
        since = evaluated_at - timedelta(
            seconds=request.evaluation_window_seconds
        )
        records = repository.telemetry(service_key, since=since)
        usable_pairs = self._traffic_points(records, evaluated_at)
        usable_records = [record for record, _ in usable_pairs]
        points = [point for _, point in usable_pairs]
        if not points:
            raise ShadowEvaluationError(
                "No usable telemetry is available for the evaluation window"
            )
        if (
            evaluated_at - _as_utc(usable_records[-1].collected_at)
        ).total_seconds() > self.settings.maximum_telemetry_age_seconds:
            raise ShadowEvaluationError("Latest telemetry is stale")
        self._check_contiguous(points)
        replayed_window_seconds = sum(
            point.window_seconds for point in points
        )
        if replayed_window_seconds < max(
            1,
            request.evaluation_window_seconds
            - self.settings.collection_interval_seconds,
        ):
            raise ShadowEvaluationError(
                "Insufficient contiguous telemetry for the requested window"
            )

        strategies = (
            (StrategyName.STATIC, float(recommendation.current_rate)),
            (StrategyName.RULE_BASED, request.rule_based_rate),
            (StrategyName.FORECAST_ASSISTED, float(recommendation.recommended_rate)),
        )
        outcomes = []
        for strategy, rate in strategies:
            result = simulate_token_buckets(
                points,
                global_bucket=TokenBucket(
                    policy.global_bucket_capacity,
                    rate,
                ),
                tenant_bucket=policy.tenant_bucket,
                route_bucket=policy.route_bucket,
            )
            outcomes.append(
                calculate_outcome(
                    strategy=strategy,
                    applied_rate=rate,
                    simulation=result,
                    points=points,
                    forecast_rps=float(recommendation.forecast_rps),
                )
            )

        actual_incoming = _weighted_mean(
            [(point.incoming_rps, point.window_seconds) for point in points]
        )
        proposed = next(
            item
            for item in outcomes
            if item.strategy == StrategyName.FORECAST_ASSISTED
        )
        metadata = {
            "simulation_version": "token-bucket-replay-1",
            "recommendation_id": str(recommendation.id),
            "current_policy_version": policy.current_policy_version,
            "tenant_route_policy_version": (
                policy.tenant_route_policy_version
            ),
            "forecast_rps": float(recommendation.forecast_rps),
            "forecast_confidence": float(recommendation.forecast_confidence),
            "requested_evaluation_window_seconds": (
                request.evaluation_window_seconds
            ),
            "replayed_evaluation_window_seconds": replayed_window_seconds,
            "initial_bucket_state": "full",
            "backend_metrics_semantics": (
                "Latency, 5xx, and CPU values below are observed under the "
                "historical workload and are not predicted for alternative policies"
            ),
            "arrival_model": (
                "Uniformly distributed arrivals within each telemetry sample "
                "window; aggregate telemetry cannot reconstruct sub-window bursts"
            ),
            "bucket_configuration": {
                "global": {
                    "capacity": policy.global_bucket_capacity,
                    "current_refill_rate_rps": policy.current_rate,
                    "proposed_refill_rate_rps": float(
                        recommendation.recommended_rate
                    ),
                },
                "tenant": {
                    "key": request.tenant_key,
                    **policy.tenant_bucket.model_dump(mode="json"),
                },
                "route": {
                    "key": request.route_key,
                    **policy.route_bucket.model_dump(mode="json"),
                },
                "assumption": (
                    "Service aggregate is replayed through one representative "
                    "tenant and route bucket; tenant/route identity is not in telemetry"
                ),
            },
            "rule_based_rate_rps": request.rule_based_rate,
            "safe_capacity_rps": request.safe_capacity_rps,
            "hard_max_refill_rate": policy.hard_max_refill_rate,
            "min_refill_rate": policy.min_refill_rate,
            "adaptive_control_enabled": policy.adaptive_control_enabled,
            "telemetry_samples": [
                {
                    "id": str(record.id),
                    "timestamp": point.timestamp.isoformat(),
                    "window_seconds": point.window_seconds,
                    "incoming_rps": point.incoming_rps,
                    "allowed_rps": point.allowed_rps,
                    "rejected_rps": point.rejected_rps,
                    "p95_latency_ms": point.p95_latency_ms,
                    "p99_latency_ms": point.p99_latency_ms,
                    "error_rate": point.error_rate,
                    "cpu_utilization": point.cpu_utilization,
                }
                for record, point in usable_pairs
            ],
        }
        result = repository.create_evaluation(
            id=uuid4(),
            recommendation_id=recommendation.id,
            service_key=service_key,
            current_policy_version=policy.current_policy_version,
            current_rate=policy.current_rate,
            proposed_rate=recommendation.recommended_rate,
            actual_incoming_rps=actual_incoming,
            estimated_admitted_rps=proposed.estimated_admitted_rps,
            estimated_rejected_rps=proposed.estimated_rejected_rps,
            evaluation_window_seconds=sum(
                point.window_seconds for point in points
            ),
            evaluation_result={
                "strategies": [
                    outcome.model_dump(mode="json") for outcome in outcomes
                ],
                "input_metadata": metadata,
            },
            created_at=evaluated_at,
        )
        return _result_schema(result)

    @staticmethod
    def compare(
        service_key: str,
        evaluations: list[ShadowEvaluationRecord],
    ) -> ShadowComparison:
        summaries = []
        for strategy in StrategyName:
            outcomes = [
                item
                for evaluation in evaluations
                for item in evaluation.evaluation_result.get("strategies", [])
                if item["strategy"] == strategy.value
            ]
            if not outcomes:
                continue
            summaries.append(
                StrategyComparison(
                    strategy=strategy,
                    evaluation_count=len(outcomes),
                    mean_admitted_rps=_mean(
                        [item["estimated_admitted_rps"] for item in outcomes]
                    ),
                    mean_rejected_rps=_mean(
                        [item["estimated_rejected_rps"] for item in outcomes]
                    ),
                    mean_observed_p95_latency_ms=_optional_mean(
                        [item.get("observed_p95_latency_ms") for item in outcomes]
                    ),
                    mean_observed_p99_latency_ms=_optional_mean(
                        [item.get("observed_p99_latency_ms") for item in outcomes]
                    ),
                    mean_observed_error_rate=_optional_mean(
                        [item.get("observed_error_rate") for item in outcomes]
                    ),
                    mean_observed_cpu_utilization=_optional_mean(
                        [item.get("observed_cpu_utilization") for item in outcomes]
                    ),
                    mean_forecast_error_rps=_optional_mean(
                        [item.get("forecast_error_rps") for item in outcomes]
                    ),
                    policy_rate_changes=_rate_changes(
                        evaluations,
                        strategy,
                    ),
                )
            )
        return ShadowComparison(service_key=service_key, strategies=summaries)

    def _traffic_points(
        self,
        records: list[TelemetrySampleRecord],
        now: datetime,
    ) -> list[tuple[TelemetrySampleRecord, TrafficPoint]]:
        usable = [
            record
            for record in records
            if record.incoming_rps is not None
            and record.data_quality not in {"stale", "missing", "invalid"}
            and _as_utc(record.window_start) + timedelta(
                seconds=record.window_seconds
            )
            <= now
        ]
        return [
            (
                record,
                TrafficPoint(
                    timestamp=record.window_start,
                    window_seconds=record.window_seconds,
                    incoming_rps=float(record.incoming_rps),
                    allowed_rps=_float_or_none(record.allowed_rps),
                    rejected_rps=_float_or_none(record.rejected_rps),
                    p95_latency_ms=_float_or_none(record.p95_latency_ms),
                    p99_latency_ms=_float_or_none(record.p99_latency_ms),
                    error_rate=_float_or_none(record.error_rate),
                    cpu_utilization=_float_or_none(record.cpu_utilization),
                ),
            )
            for record in usable
        ]

    @staticmethod
    def _check_contiguous(points: list[TrafficPoint]) -> None:
        for previous, current in zip(points, points[1:]):
            expected = _as_utc(previous.timestamp) + timedelta(
                seconds=previous.window_seconds
            )
            if _as_utc(current.timestamp) != expected:
                raise ShadowEvaluationError(
                    "Telemetry contains gaps; refusing an incomplete replay"
                )


def _result_schema(
    record: ShadowEvaluationRecord,
) -> ShadowEvaluationResult:
    values = {
        key: getattr(record, key)
        for key in (
            "id",
            "recommendation_id",
            "service_key",
            "current_policy_version",
            "current_rate",
            "proposed_rate",
            "actual_incoming_rps",
            "estimated_admitted_rps",
            "estimated_rejected_rps",
            "evaluation_window_seconds",
            "created_at",
        )
    }
    values.update(record.evaluation_result)
    return ShadowEvaluationResult.model_validate(values)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _float_or_none(value: float | None) -> float | None:
    return None if value is None else float(value)


def _weighted_mean(values: list[tuple[float, int]]) -> float:
    duration = sum(weight for _, weight in values)
    return sum(value * weight for value, weight in values) / duration


def _mean(values: list[float]) -> float:
    return sum(values) / len(values)


def _optional_mean(values: list[float | None]) -> float | None:
    present = [value for value in values if value is not None]
    return _mean(present) if present else None


def _rate_changes(
    evaluations: list[ShadowEvaluationRecord],
    strategy: StrategyName,
) -> int:
    chronological = sorted(evaluations, key=lambda item: item.created_at)
    rates = [
        item["applied_global_rate_rps"]
        for evaluation in chronological
        for item in evaluation.evaluation_result.get("strategies", [])
        if item["strategy"] == strategy.value
    ]
    return sum(
        previous != current
        for previous, current in zip(rates, rates[1:])
    )
