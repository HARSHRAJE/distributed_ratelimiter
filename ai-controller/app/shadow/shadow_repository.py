from datetime import datetime
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.shadow.schemas import BucketConfiguration
from app.telemetry.models import (
    PolicyRecommendationRecord,
    RecommendationValidationRecord,
    ShadowEvaluationRecord,
    TelemetrySampleRecord,
)


@dataclass(frozen=True)
class PolicySnapshot:
    current_policy_version: int
    tenant_route_policy_version: int
    current_rate: float
    global_bucket_capacity: int
    hard_max_refill_rate: float
    adaptive_control_enabled: bool
    min_refill_rate: float
    tenant_bucket: BucketConfiguration
    route_bucket: BucketConfiguration


class ShadowRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def recommendation(
        self,
        recommendation_id: UUID,
    ) -> PolicyRecommendationRecord | None:
        return self.session.get(PolicyRecommendationRecord, recommendation_id)

    def latest_validation(
        self,
        recommendation_id: UUID,
    ) -> RecommendationValidationRecord | None:
        return self.session.scalar(
            select(RecommendationValidationRecord)
            .where(
                RecommendationValidationRecord.recommendation_id
                == recommendation_id
            )
            .order_by(
                RecommendationValidationRecord.validated_at.desc(),
                RecommendationValidationRecord.id.desc(),
            )
            .limit(1)
        )

    def policy_snapshot(
        self,
        service_key: str,
        *,
        tenant_key: str,
        route_key: str,
    ) -> PolicySnapshot | None:
        row = self.session.execute(
            text(
                """
                SELECT s.config_version,
                       s.global_refill_rate,
                       s.global_capacity,
                       s.hard_max_refill_rate,
                       s.adaptive_enabled,
                       v.version AS tenant_route_policy_version,
                       v.min_refill_rate,
                       v.tenant_capacity,
                       v.tenant_refill_rate,
                       v.route_capacity,
                       v.route_refill_rate
                FROM services AS s
                JOIN rate_limit_policies AS p
                  ON p.service_id = s.id
                 AND p.tenant_id = :tenant_key
                 AND p.route_id = :route_key
                 AND p.status = 'ACTIVE'
                JOIN rate_limit_policy_versions AS v
                  ON v.policy_id = p.id
                 AND v.version = p.active_version
                WHERE s.service_key = :service_key
                """
            ),
            {
                "service_key": service_key,
                "tenant_key": tenant_key,
                "route_key": route_key,
            },
        ).mappings().one_or_none()
        if row is None:
            return None
        return PolicySnapshot(
            current_policy_version=int(row["config_version"]),
            tenant_route_policy_version=int(
                row["tenant_route_policy_version"]
            ),
            current_rate=float(row["global_refill_rate"]),
            global_bucket_capacity=int(row["global_capacity"]),
            hard_max_refill_rate=float(row["hard_max_refill_rate"]),
            adaptive_control_enabled=bool(row["adaptive_enabled"]),
            min_refill_rate=float(row["min_refill_rate"]),
            tenant_bucket=BucketConfiguration(
                capacity=int(row["tenant_capacity"]),
                refill_rate_rps=float(row["tenant_refill_rate"]),
            ),
            route_bucket=BucketConfiguration(
                capacity=int(row["route_capacity"]),
                refill_rate_rps=float(row["route_refill_rate"]),
            ),
        )

    def telemetry(
        self,
        service_key: str,
        *,
        since: datetime,
    ) -> list[TelemetrySampleRecord]:
        return list(
            self.session.scalars(
                select(TelemetrySampleRecord)
                .where(
                    TelemetrySampleRecord.service_key == service_key,
                    TelemetrySampleRecord.window_start >= since,
                )
                .order_by(TelemetrySampleRecord.window_start)
            ).all()
        )

    def create_evaluation(
        self,
        **values: Any,
    ) -> ShadowEvaluationRecord:
        record = ShadowEvaluationRecord(**values)
        self.session.add(record)
        self.session.commit()
        self.session.refresh(record)
        return record

    def get_evaluation(self, evaluation_id: UUID) -> ShadowEvaluationRecord | None:
        return self.session.get(ShadowEvaluationRecord, evaluation_id)

    def latest(self, service_key: str) -> ShadowEvaluationRecord | None:
        return self.session.scalar(
            select(ShadowEvaluationRecord)
            .where(ShadowEvaluationRecord.service_key == service_key)
            .order_by(ShadowEvaluationRecord.created_at.desc())
            .limit(1)
        )

    def history(
        self,
        service_key: str,
        *,
        limit: int,
    ) -> list[ShadowEvaluationRecord]:
        return list(
            self.session.scalars(
                select(ShadowEvaluationRecord)
                .where(ShadowEvaluationRecord.service_key == service_key)
                .order_by(ShadowEvaluationRecord.created_at.desc())
                .limit(limit)
            ).all()
        )
