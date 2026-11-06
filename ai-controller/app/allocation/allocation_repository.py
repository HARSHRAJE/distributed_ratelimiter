from datetime import datetime
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.allocation.evaluation import evaluate_allocations
from app.allocation.schemas import (
    AllocationMetrics,
    AllocationRun,
    TenantAllocationConfig,
    TenantAllocationConfigList,
)
from app.allocation.weighted_allocator import weighted_water_fill
from app.telemetry.models import (
    TenantAllocationConfigRecord,
    TenantAllocationResultRecord,
    TenantAllocationRunRecord,
)


class AllocationRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def save_configs(
        self,
        service_key: str,
        configs: TenantAllocationConfigList,
        *,
        now: datetime,
    ) -> list[TenantAllocationConfigRecord]:
        with self.session.begin():
            self._lock_service(service_key)
            current = {
                item.tenant_id: item
                for item in self.session.scalars(
                    select(TenantAllocationConfigRecord).where(
                        TenantAllocationConfigRecord.service_key == service_key
                    )
                ).all()
            }
            requested_ids = {item.tenant_id for item in configs.tenants}
            for tenant_id, record in current.items():
                if tenant_id not in requested_ids:
                    self.session.delete(record)
            saved = []
            for config in configs.tenants:
                record = current.get(config.tenant_id)
                if record is None:
                    record = TenantAllocationConfigRecord(
                        id=uuid4(),
                        service_key=service_key,
                        tenant_id=config.tenant_id,
                        created_at=now,
                    )
                    self.session.add(record)
                record.priority = config.tenant_priority
                record.weight = config.weight
                record.minimum_rate = config.minimum_rate
                record.maximum_rate = config.maximum_rate
                record.adaptive_enabled = config.adaptive_enabled
                record.predicted_demand = config.predicted_demand
                record.current_allocation = config.current_allocation
                record.updated_at = now
                saved.append(record)
            self.session.flush()
        return saved

    def configs(self, service_key: str) -> list[TenantAllocationConfigRecord]:
        return list(
            self.session.scalars(
                select(TenantAllocationConfigRecord)
                .where(TenantAllocationConfigRecord.service_key == service_key)
                .order_by(TenantAllocationConfigRecord.tenant_id)
            ).all()
        )

    def evaluate(
        self,
        service_key: str,
        global_capacity: Decimal,
        *,
        now: datetime,
    ) -> AllocationRun:
        with self.session.begin():
            self._lock_service(service_key)
            config_records = list(
                self.session.scalars(
                    select(TenantAllocationConfigRecord)
                    .where(TenantAllocationConfigRecord.service_key == service_key)
                    .order_by(TenantAllocationConfigRecord.tenant_id)
                    .with_for_update()
                ).all()
            )
            configs = [
                TenantAllocationConfig(
                    tenant_id=record.tenant_id,
                    tenant_priority=record.priority,
                    weight=record.weight,
                    minimum_rate=record.minimum_rate,
                    maximum_rate=record.maximum_rate,
                    adaptive_enabled=record.adaptive_enabled,
                    predicted_demand=record.predicted_demand,
                    current_allocation=record.current_allocation,
                )
                for record in config_records
            ]
            allocations = weighted_water_fill(configs, global_capacity)
            previous_run = self.session.scalar(
                select(TenantAllocationRunRecord)
                .where(TenantAllocationRunRecord.service_key == service_key)
                .order_by(
                    TenantAllocationRunRecord.allocation_version.desc()
                )
                .limit(1)
            )
            previous_records = []
            if previous_run is not None:
                previous_records = list(
                    self.session.scalars(
                        select(TenantAllocationResultRecord).where(
                            TenantAllocationResultRecord.allocation_run_id
                            == previous_run.id
                        )
                    ).all()
                )
            previous_allocations = {
                item.tenant_id: Decimal(item.allocation_rate)
                for item in previous_records
            }
            metrics = evaluate_allocations(
                allocations,
                configs,
                global_capacity,
                previous_allocations=(
                    previous_allocations if previous_run is not None else None
                ),
                starvation_seconds=self._starvation_duration(
                    service_key,
                    allocations,
                    now,
                ),
            )
            version = (
                self.session.scalar(
                    select(func.max(TenantAllocationRunRecord.allocation_version))
                    .where(TenantAllocationRunRecord.service_key == service_key)
                )
                or 0
            ) + 1
            run = TenantAllocationRunRecord(
                id=uuid4(),
                service_key=service_key,
                allocation_version=version,
                global_capacity=global_capacity,
                evaluation_metrics=metrics.model_dump(mode="json"),
                created_at=now,
            )
            self.session.add(run)
            self.session.flush()
            config_by_tenant = {
                item.tenant_id: item
                for item in configs
            }
            for allocation in allocations:
                config = config_by_tenant[allocation.tenant_id]
                self.session.add(
                    TenantAllocationResultRecord(
                        id=uuid4(),
                        allocation_run_id=run.id,
                        service_key=service_key,
                        tenant_id=allocation.tenant_id,
                        allocation_rate=allocation.allocation_rate,
                        predicted_demand=allocation.predicted_demand,
                        current_allocation=allocation.current_allocation,
                        priority=allocation.tenant_priority,
                        weight=allocation.weight,
                        minimum_rate=config.minimum_rate,
                        maximum_rate=config.maximum_rate,
                        adaptive_enabled=config.adaptive_enabled,
                        global_capacity=global_capacity,
                        allocation_version=version,
                        created_at=now,
                    )
                )
            self.session.flush()
            output = self._map_run(run, allocations)
        return output

    def latest(self, service_key: str) -> AllocationRun | None:
        run = self.session.scalar(
            select(TenantAllocationRunRecord)
            .where(TenantAllocationRunRecord.service_key == service_key)
            .order_by(TenantAllocationRunRecord.allocation_version.desc())
            .limit(1)
        )
        return self._map_recorded_run(run) if run is not None else None

    def history(self, service_key: str, *, limit: int) -> list[AllocationRun]:
        runs = list(
            self.session.scalars(
                select(TenantAllocationRunRecord)
                .where(TenantAllocationRunRecord.service_key == service_key)
                .order_by(TenantAllocationRunRecord.allocation_version.desc())
                .limit(limit)
            ).all()
        )
        return [self._map_recorded_run(run) for run in runs]

    def _lock_service(self, service_key: str) -> None:
        if self.session.get_bind().dialect.name == "postgresql":
            self.session.execute(
                text("SELECT pg_advisory_xact_lock(hashtext(:service_key))"),
                {"service_key": service_key},
            )

    def _starvation_duration(
        self,
        service_key: str,
        allocations,
        now: datetime,
    ) -> int:
        starved = {
            item.tenant_id
            for item in allocations
            if item.predicted_demand > 0 and item.allocation_rate == 0
        }
        if not starved:
            return 0
        runs = list(
            self.session.scalars(
                select(TenantAllocationRunRecord)
                .where(TenantAllocationRunRecord.service_key == service_key)
                .order_by(TenantAllocationRunRecord.allocation_version.desc())
                .limit(100)
            ).all()
        )
        oldest = now
        for run in runs:
            allocated = set(
                self.session.scalars(
                    select(TenantAllocationResultRecord.tenant_id).where(
                        TenantAllocationResultRecord.allocation_run_id == run.id,
                        TenantAllocationResultRecord.allocation_rate == 0,
                        TenantAllocationResultRecord.predicted_demand > 0,
                    )
                ).all()
            )
            if not starved.issubset(allocated):
                break
            oldest = run.created_at
        return max(0, int((now - oldest).total_seconds()))

    def _map_recorded_run(self, run: TenantAllocationRunRecord) -> AllocationRun:
        records = list(
            self.session.scalars(
                select(TenantAllocationResultRecord)
                .where(TenantAllocationResultRecord.allocation_run_id == run.id)
                .order_by(TenantAllocationResultRecord.tenant_id)
            ).all()
        )
        allocations = []
        for record in records:
            allocations.append(
                {
                    "tenant_id": record.tenant_id,
                    "allocation_rate": record.allocation_rate,
                    "predicted_demand": record.predicted_demand,
                    "current_allocation": record.current_allocation,
                    "tenant_priority": record.priority,
                    "weight": record.weight,
                }
            )
        return AllocationRun(
            allocation_run_id=run.id,
            service_key=run.service_key,
            allocation_version=run.allocation_version,
            global_capacity_rps=run.global_capacity,
            allocations=allocations,
            metrics=AllocationMetrics.model_validate(run.evaluation_metrics),
            created_at=run.created_at,
        )

    @staticmethod
    def _map_run(run, allocations) -> AllocationRun:
        return AllocationRun(
            allocation_run_id=run.id,
            service_key=run.service_key,
            allocation_version=run.allocation_version,
            global_capacity_rps=run.global_capacity,
            allocations=allocations,
            metrics=AllocationMetrics.model_validate(run.evaluation_metrics),
            created_at=run.created_at,
        )
