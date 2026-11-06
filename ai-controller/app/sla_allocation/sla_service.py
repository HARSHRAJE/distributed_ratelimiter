from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.route_allocation.schemas import RouteAllocationConfig
from app.sla_allocation.evaluation import evaluate_sla_allocations
from app.sla_allocation.guarantee_validator import (
    SlaGuaranteeError,
    validate_guarantees,
)
from app.sla_allocation.schemas import (
    ServiceTier,
    SlaAllocationHistory,
    SlaAllocationMetrics,
    SlaAllocationRun,
    SlaComplianceReport,
    SlaTenantAllocation,
    TenantSlaCompliance,
    TenantSlaConfig,
    TenantSlaConfigInput,
    TenantSlaConfigList,
)
from app.sla_allocation.sla_allocator import allocate_sla_capacity
from app.telemetry.models import (
    RouteAllocationConfigRecord,
    TenantSlaAllocationResultRecord,
    TenantSlaAllocationRunRecord,
    TenantSlaConfigRecord,
    TenantSlaConfigVersionRecord,
)


class SlaService:
    def replace_configs(
        self,
        service_key: str,
        configs: TenantSlaConfigList,
        *,
        session: Session,
        now: datetime | None = None,
    ) -> list[TenantSlaConfig]:
        current_time = now or datetime.now(timezone.utc)
        with session.begin():
            self._lock_service(session, service_key)
            records = {
                item.tenant_id: item
                for item in session.scalars(
                    select(TenantSlaConfigRecord)
                    .where(TenantSlaConfigRecord.service_key == service_key)
                    .with_for_update()
                ).all()
            }
            results = []
            for config in configs.tenants:
                record = records.get(config.tenant_id)
                if record is None:
                    record = TenantSlaConfigRecord(
                        id=uuid4(),
                        service_key=service_key,
                        tenant_id=config.tenant_id,
                        config_version=1,
                        created_at=current_time,
                        updated_at=current_time,
                    )
                    session.add(record)
                    version = 1
                    create_snapshot = True
                else:
                    create_snapshot = self._config_differs(record, config)
                    version = record.config_version + (
                        1 if create_snapshot else 0
                    )
                    record.config_version = version
                    record.updated_at = current_time
                self._apply_config(record, config)
                if create_snapshot:
                    session.add(
                        self._version_snapshot(
                            record,
                            config,
                            version,
                            current_time,
                        )
                    )
                results.append(record)
            session.flush()
            output = [
                TenantSlaConfig.model_validate(item)
                for item in results
            ]
        return output

    @staticmethod
    def list_configs(
        service_key: str,
        *,
        session: Session,
    ) -> list[TenantSlaConfig]:
        records = session.scalars(
            select(TenantSlaConfigRecord)
            .where(TenantSlaConfigRecord.service_key == service_key)
            .order_by(TenantSlaConfigRecord.tenant_id)
        ).all()
        return [TenantSlaConfig.model_validate(item) for item in records]

    @staticmethod
    def get_config(
        service_key: str,
        tenant_id: str,
        *,
        session: Session,
    ) -> TenantSlaConfig | None:
        record = session.scalar(
            select(TenantSlaConfigRecord).where(
                TenantSlaConfigRecord.service_key == service_key,
                TenantSlaConfigRecord.tenant_id == tenant_id,
            )
        )
        return TenantSlaConfig.model_validate(record) if record else None

    def evaluate(
        self,
        service_key: str,
        capacity: Decimal,
        *,
        session: Session,
        now: datetime | None = None,
    ) -> SlaAllocationRun:
        current_time = now or datetime.now(timezone.utc)
        with session.begin():
            self._lock_service(session, service_key)
            records = session.scalars(
                select(TenantSlaConfigRecord)
                .where(TenantSlaConfigRecord.service_key == service_key)
                .order_by(TenantSlaConfigRecord.tenant_id)
                .with_for_update()
            ).all()
            configs = [self._input_from_record(item) for item in records]
            validate_guarantees(configs, capacity)
            rates = allocate_sla_capacity(configs, capacity)
            self._validate_route_minimums(
                service_key,
                configs,
                rates,
                session=session,
            )
            config_versions = {
                item.tenant_id: item.config_version for item in records
            }
            allocations, metrics = evaluate_sla_allocations(
                configs,
                rates,
                capacity=capacity,
                config_versions=config_versions,
            )
            version = (
                session.scalar(
                    select(func.max(TenantSlaAllocationRunRecord.allocation_version))
                    .where(TenantSlaAllocationRunRecord.service_key == service_key)
                )
                or 0
            ) + 1
            run = TenantSlaAllocationRunRecord(
                id=uuid4(),
                service_key=service_key,
                allocation_version=version,
                global_capacity=capacity,
                evaluation_metrics=metrics.model_dump(mode="json"),
                created_at=current_time,
            )
            session.add(run)
            session.flush()
            snapshots = {
                item.tenant_id: session.scalar(
                    select(TenantSlaConfigVersionRecord).where(
                        TenantSlaConfigVersionRecord.config_id == item.id,
                        TenantSlaConfigVersionRecord.config_version
                        == item.config_version,
                    )
                )
                for item in records
            }
            for allocation in allocations:
                config = next(
                    item for item in configs
                    if item.tenant_id == allocation.tenant_id
                )
                snapshot = snapshots[allocation.tenant_id]
                if snapshot is None:
                    raise RuntimeError(
                        "Tenant SLA configuration version snapshot is missing"
                    )
                session.add(
                    TenantSlaAllocationResultRecord(
                        id=uuid4(),
                        allocation_run_id=run.id,
                        config_version_id=snapshot.id,
                        service_key=service_key,
                        tenant_id=allocation.tenant_id,
                        config_version=allocation.config_version,
                        tier=allocation.tier.value,
                        priority=allocation.priority,
                        allocation_weight=allocation.allocation_weight,
                        guaranteed_rate=allocation.guaranteed_rate,
                        allocated_rate=allocation.allocated_rate,
                        maximum_rate=allocation.maximum_rate,
                        predicted_demand=allocation.predicted_demand,
                        max_throttle_ratio=allocation.max_throttle_ratio,
                        tenant_burst_capacity=(
                            allocation.tenant_burst_capacity
                        ),
                        availability_target=allocation.availability_target,
                        adaptive_enabled=allocation.adaptive_enabled,
                        projected_throttle_ratio=(
                            allocation.projected_throttle_ratio
                        ),
                        resource_usage=None,
                        created_at=current_time,
                    )
                )
            session.flush()
            return SlaAllocationRun(
                allocation_run_id=run.id,
                service_key=service_key,
                allocation_version=version,
                global_service_capacity=capacity,
                allocations=allocations,
                metrics=metrics,
                created_at=current_time,
            )

    @staticmethod
    def history(
        service_key: str,
        *,
        session: Session,
        limit: int,
    ) -> SlaAllocationHistory:
        runs = session.scalars(
            select(TenantSlaAllocationRunRecord)
            .where(TenantSlaAllocationRunRecord.service_key == service_key)
            .order_by(
                TenantSlaAllocationRunRecord.allocation_version.desc()
            )
            .limit(limit)
        ).all()
        return SlaAllocationHistory(
            service_key=service_key,
            runs=[
                SlaService._map_run(item, session=session)
                for item in runs
            ],
        )

    @staticmethod
    def compliance(
        service_key: str,
        *,
        session: Session,
    ) -> SlaComplianceReport:
        run = session.scalar(
            select(TenantSlaAllocationRunRecord)
            .where(TenantSlaAllocationRunRecord.service_key == service_key)
            .order_by(TenantSlaAllocationRunRecord.allocation_version.desc())
            .limit(1)
        )
        current_configs = {
            item.tenant_id: item
            for item in session.scalars(
                select(TenantSlaConfigRecord).where(
                    TenantSlaConfigRecord.service_key == service_key
                )
            ).all()
        }
        proposal_records = (
            session.scalars(
                select(TenantSlaAllocationResultRecord).where(
                    TenantSlaAllocationResultRecord.allocation_run_id == run.id
                )
            ).all()
            if run is not None
            else []
        )
        proposals = {item.tenant_id: item for item in proposal_records}
        violation_counts = dict(
            session.execute(
                select(
                    TenantSlaAllocationResultRecord.tenant_id,
                    func.count(TenantSlaAllocationResultRecord.id),
                )
                .join(
                    TenantSlaConfigVersionRecord,
                    TenantSlaConfigVersionRecord.id
                    == TenantSlaAllocationResultRecord.config_version_id,
                )
                .where(
                    TenantSlaAllocationResultRecord.service_key == service_key,
                    TenantSlaAllocationResultRecord.allocated_rate
                    < TenantSlaAllocationResultRecord.guaranteed_rate,
                )
                .group_by(TenantSlaAllocationResultRecord.tenant_id)
            ).all()
        )
        tenants = []
        for tenant_id, config in sorted(current_configs.items()):
            proposal = proposals.get(tenant_id)
            tenants.append(
                TenantSlaCompliance(
                    tenant_id=tenant_id,
                    tier=ServiceTier(config.tier),
                    config_version=config.config_version,
                    guaranteed_rate=config.minimum_guaranteed_rate,
                    proposed_allocation_rps=(
                        Decimal(proposal.allocated_rate)
                        if proposal is not None
                        else None
                    ),
                    proposal_guarantee_violations=violation_counts.get(
                        tenant_id,
                        0,
                    ),
                    actual_admitted_rps=None,
                    actual_throttle_ratio=None,
                    measured_resource_usage=None,
                    p95_latency_ms=None,
                    error_rate=None,
                    availability=None,
                    max_throttle_ratio=config.max_throttle_ratio,
                    availability_target=config.availability_target,
                    sla_compliance="NOT_MEASURABLE",
                    measurement_note=(
                        "Available telemetry is service-wide and is not "
                        "tenant-scoped; allocation proposals do not establish "
                        "actual throughput, latency, errors, or availability."
                    ),
                )
            )
        return SlaComplianceReport(
            service_key=service_key,
            allocation_run_id=run.id if run is not None else None,
            tenants=tenants,
        )

    @staticmethod
    def _map_run(
        run: TenantSlaAllocationRunRecord,
        *,
        session: Session,
    ) -> SlaAllocationRun:
        records = session.scalars(
            select(TenantSlaAllocationResultRecord)
            .where(TenantSlaAllocationResultRecord.allocation_run_id == run.id)
            .order_by(TenantSlaAllocationResultRecord.tenant_id)
        ).all()
        allocations = [
            SlaTenantAllocation(
                tenant_id=item.tenant_id,
                tier=ServiceTier(item.tier),
                priority=item.priority,
                allocation_weight=item.allocation_weight,
                config_version=item.config_version,
                guaranteed_rate=item.guaranteed_rate,
                allocated_rate=item.allocated_rate,
                maximum_rate=item.maximum_rate,
                predicted_demand=item.predicted_demand,
                max_throttle_ratio=item.max_throttle_ratio,
                projected_throttle_ratio=item.projected_throttle_ratio,
                estimated_resource_usage=item.resource_usage,
                guarantee_met=item.allocated_rate >= item.guaranteed_rate,
                projected_throttle_within_sla=(
                    item.projected_throttle_ratio <= item.max_throttle_ratio
                ),
                tenant_burst_capacity=item.tenant_burst_capacity,
                availability_target=item.availability_target,
                adaptive_enabled=item.adaptive_enabled,
            )
            for item in records
        ]
        return SlaAllocationRun(
            allocation_run_id=run.id,
            service_key=run.service_key,
            allocation_version=run.allocation_version,
            global_service_capacity=run.global_capacity,
            allocations=allocations,
            metrics=SlaAllocationMetrics.model_validate(
                run.evaluation_metrics
            ),
            created_at=run.created_at,
        )

    @staticmethod
    def _validate_route_minimums(
        service_key: str,
        configs: list[TenantSlaConfigInput],
        allocations: dict[str, Decimal],
        *,
        session: Session,
    ) -> None:
        route_configs = session.scalars(
            select(RouteAllocationConfigRecord).where(
                RouteAllocationConfigRecord.service_key == service_key
            )
        ).all()
        guaranteed = {
            item.tenant_id: item.minimum_guaranteed_rate
            for item in configs
        }
        route_minimums: dict[str, Decimal] = {}
        for route in route_configs:
            if route.tenant_id not in guaranteed:
                raise SlaGuaranteeError(
                    f"Route allocation tenant {route.tenant_id} has no SLA configuration"
                )
            route_minimums[route.tenant_id] = (
                route_minimums.get(route.tenant_id, Decimal(0))
                + (
                    Decimal(route.current_allocation)
                    if not route.adaptive_enabled
                    else Decimal(route.minimum_rate)
                )
            )
        for tenant_id, route_minimum in route_minimums.items():
            if (
                tenant_id in allocations
                and route_minimum > allocations[tenant_id]
            ):
                raise SlaGuaranteeError(
                    f"Route minimums for tenant {tenant_id} exceed its "
                    "proposed SLA allocation"
                )

    @staticmethod
    def _lock_service(session: Session, service_key: str) -> None:
        if session.get_bind().dialect.name == "postgresql":
            session.execute(
                text("SELECT pg_advisory_xact_lock(hashtext(:service_key))"),
                {"service_key": service_key},
            )

    @staticmethod
    def _input_from_record(
        record: TenantSlaConfigRecord,
    ) -> TenantSlaConfigInput:
        return TenantSlaConfigInput(
            tenant_id=record.tenant_id,
            tier=ServiceTier(record.tier),
            priority=record.priority,
            allocation_weight=record.allocation_weight,
            minimum_guaranteed_rate=record.minimum_guaranteed_rate,
            maximum_rate=record.maximum_rate,
            max_throttle_ratio=record.max_throttle_ratio,
            tenant_burst_capacity=record.tenant_burst_capacity,
            availability_target=record.availability_target,
            adaptive_enabled=record.adaptive_enabled,
            predicted_demand=record.predicted_demand,
        )

    @staticmethod
    def _config_differs(
        record: TenantSlaConfigRecord,
        config: TenantSlaConfigInput,
    ) -> bool:
        return any(
            (
                record.tier != config.tier.value,
                record.priority != config.priority,
                Decimal(record.allocation_weight) != config.allocation_weight,
                Decimal(record.minimum_guaranteed_rate)
                != config.minimum_guaranteed_rate,
                Decimal(record.maximum_rate) != config.maximum_rate,
                Decimal(record.max_throttle_ratio)
                != config.max_throttle_ratio,
                record.tenant_burst_capacity != config.tenant_burst_capacity,
                Decimal(record.availability_target)
                != config.availability_target,
                record.adaptive_enabled != config.adaptive_enabled,
                Decimal(record.predicted_demand) != config.predicted_demand,
            )
        )

    @staticmethod
    def _apply_config(
        record: TenantSlaConfigRecord,
        config: TenantSlaConfigInput,
    ) -> None:
        record.tier = config.tier.value
        record.priority = config.priority
        record.allocation_weight = config.allocation_weight
        record.minimum_guaranteed_rate = config.minimum_guaranteed_rate
        record.maximum_rate = config.maximum_rate
        record.max_throttle_ratio = config.max_throttle_ratio
        record.tenant_burst_capacity = config.tenant_burst_capacity
        record.availability_target = config.availability_target
        record.adaptive_enabled = config.adaptive_enabled
        record.predicted_demand = config.predicted_demand

    @staticmethod
    def _version_snapshot(
        record: TenantSlaConfigRecord,
        config: TenantSlaConfigInput,
        version: int,
        now: datetime,
    ) -> TenantSlaConfigVersionRecord:
        return TenantSlaConfigVersionRecord(
            id=uuid4(),
            config_id=record.id,
            service_key=record.service_key,
            tenant_id=record.tenant_id,
            config_version=version,
            tier=config.tier.value,
            priority=config.priority,
            allocation_weight=config.allocation_weight,
            minimum_guaranteed_rate=config.minimum_guaranteed_rate,
            maximum_rate=config.maximum_rate,
            max_throttle_ratio=config.max_throttle_ratio,
            tenant_burst_capacity=config.tenant_burst_capacity,
            availability_target=config.availability_target,
            adaptive_enabled=config.adaptive_enabled,
            predicted_demand=config.predicted_demand,
            created_at=now,
        )
