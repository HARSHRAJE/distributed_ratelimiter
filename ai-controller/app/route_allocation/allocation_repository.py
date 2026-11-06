from datetime import datetime
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.route_allocation.evaluation import evaluate_route_allocations
from app.route_allocation.multi_route_allocator import allocate_routes
from app.route_allocation.resource_constraints import (
    RouteAllocationConstraintError,
)
from app.route_allocation.schemas import (
    RouteAllocation,
    RouteAllocationComparison,
    RouteAllocationConfig,
    RouteAllocationConfigList,
    RouteAllocationMetrics,
    RouteAllocationRun,
)
from app.telemetry.models import (
    RouteAllocationConfigRecord,
    RouteAllocationResultRecord,
    RouteAllocationRunRecord,
    TenantAllocationResultRecord,
    TenantAllocationRunRecord,
)


class RouteAllocationRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def replace_configs(
        self,
        service_key: str,
        configs: RouteAllocationConfigList,
        *,
        now: datetime,
    ) -> list[RouteAllocationConfig]:
        with self.session.begin():
            self._lock_service(service_key)
            current = {
                (item.tenant_id, item.route_id): item
                for item in self.session.scalars(
                    select(RouteAllocationConfigRecord).where(
                        RouteAllocationConfigRecord.service_key == service_key
                    )
                ).all()
            }
            requested = {
                (item.tenant_id, item.route_id)
                for item in configs.routes
            }
            for scope, record in current.items():
                if scope not in requested:
                    self.session.delete(record)
            saved = []
            for config in configs.routes:
                scope = (config.tenant_id, config.route_id)
                record = current.get(scope)
                if record is None:
                    record = RouteAllocationConfigRecord(
                        id=uuid4(),
                        service_key=service_key,
                        tenant_id=config.tenant_id,
                        route_id=config.route_id,
                        created_at=now,
                    )
                    self.session.add(record)
                self._apply_config(record, config, now)
                saved.append(config)
        return saved

    def configs(self, service_key: str) -> list[RouteAllocationConfig]:
        records = self.session.scalars(
            select(RouteAllocationConfigRecord)
            .where(RouteAllocationConfigRecord.service_key == service_key)
            .order_by(
                RouteAllocationConfigRecord.tenant_id,
                RouteAllocationConfigRecord.route_id,
            )
        ).all()
        return [self._config_from_record(record) for record in records]

    def evaluate(
        self,
        service_key: str,
        backend_resource_budget: Decimal,
        *,
        now: datetime,
    ) -> RouteAllocationRun:
        with self.session.begin():
            self._lock_service(service_key)
            tenant_run = self.session.scalar(
                select(TenantAllocationRunRecord)
                .where(TenantAllocationRunRecord.service_key == service_key)
                .order_by(TenantAllocationRunRecord.allocation_version.desc())
                .limit(1)
                .with_for_update()
            )
            if tenant_run is None:
                raise RouteAllocationConstraintError(
                    "A tenant allocation run is required before route allocation"
                )
            tenant_records = self.session.scalars(
                select(TenantAllocationResultRecord).where(
                    TenantAllocationResultRecord.allocation_run_id
                    == tenant_run.id
                )
            ).all()
            tenant_limits = {
                item.tenant_id: Decimal(item.allocation_rate)
                for item in tenant_records
            }
            configs_records = self.session.scalars(
                select(RouteAllocationConfigRecord)
                .where(
                    RouteAllocationConfigRecord.service_key == service_key
                )
                .order_by(
                    RouteAllocationConfigRecord.tenant_id,
                    RouteAllocationConfigRecord.route_id,
                )
                .with_for_update()
            ).all()
            configs = [
                self._config_from_record(item)
                for item in configs_records
            ]
            global_capacity = Decimal(tenant_run.global_capacity)
            rates = allocate_routes(
                configs,
                tenant_limits,
                global_capacity,
                backend_resource_budget,
            )
            allocations, metrics = evaluate_route_allocations(
                configs,
                rates,
                tenant_limits,
                global_capacity,
                backend_resource_budget,
            )
            version = (
                self.session.scalar(
                    select(func.max(RouteAllocationRunRecord.allocation_version))
                    .where(RouteAllocationRunRecord.service_key == service_key)
                )
                or 0
            ) + 1
            run = RouteAllocationRunRecord(
                id=uuid4(),
                service_key=service_key,
                allocation_version=version,
                tenant_allocation_run_id=tenant_run.id,
                global_capacity=global_capacity,
                backend_resource_budget=backend_resource_budget,
                evaluation_metrics=metrics.model_dump(mode="json"),
                created_at=now,
            )
            self.session.add(run)
            self.session.flush()
            config_by_scope = {
                (config.tenant_id, config.route_id): config
                for config in configs
            }
            for allocation in allocations:
                config = config_by_scope[
                    (allocation.tenant_id, allocation.route_id)
                ]
                self.session.add(
                    RouteAllocationResultRecord(
                        id=uuid4(),
                        allocation_run_id=run.id,
                        service_key=service_key,
                        tenant_id=allocation.tenant_id,
                        route_id=allocation.route_id,
                        allocated_rate=allocation.allocated_rate,
                        predicted_demand=allocation.predicted_demand,
                        estimated_resource_usage=(
                            allocation.estimated_resource_usage
                        ),
                        tenant_allocation_limit=(
                            allocation.tenant_allocation_limit
                        ),
                        route_weight=config.route_weight,
                        resource_cost_factor=config.resource_cost_factor,
                        priority=config.priority,
                        minimum_rate=config.route_minimum_rate,
                        maximum_rate=config.route_maximum_rate,
                        adaptive_enabled=config.adaptive_enabled,
                        created_at=now,
                    )
                )
            self.session.flush()
            result = RouteAllocationRun(
                allocation_run_id=run.id,
                service_key=service_key,
                allocation_version=version,
                tenant_allocation_run_id=tenant_run.id,
                global_capacity=global_capacity,
                backend_resource_budget=backend_resource_budget,
                allocations=allocations,
                metrics=metrics,
                created_at=now,
            )
        return result

    def latest(self, service_key: str) -> RouteAllocationRun | None:
        record = self.session.scalar(
            select(RouteAllocationRunRecord)
            .where(RouteAllocationRunRecord.service_key == service_key)
            .order_by(RouteAllocationRunRecord.allocation_version.desc())
            .limit(1)
        )
        return self._map_run(record) if record is not None else None

    def history(self, service_key: str, *, limit: int) -> list[RouteAllocationRun]:
        records = self.session.scalars(
            select(RouteAllocationRunRecord)
            .where(RouteAllocationRunRecord.service_key == service_key)
            .order_by(RouteAllocationRunRecord.allocation_version.desc())
            .limit(limit)
        ).all()
        return [self._map_run(record) for record in records]

    def comparison(self, service_key: str) -> RouteAllocationComparison | None:
        runs = self.history(service_key, limit=2)
        if len(runs) < 2:
            return None
        previous, proposed = runs[1], runs[0]
        old = {
            (item.tenant_id, item.route_id): item.allocated_rate
            for item in previous.allocations
        }
        new = {
            (item.tenant_id, item.route_id): item.allocated_rate
            for item in proposed.allocations
        }
        changes = [
            {
                "tenant_id": tenant_id,
                "route_id": route_id,
                "previous_rate": old.get((tenant_id, route_id), Decimal(0)),
                "proposed_rate": new.get((tenant_id, route_id), Decimal(0)),
                "change_rate": (
                    new.get((tenant_id, route_id), Decimal(0))
                    - old.get((tenant_id, route_id), Decimal(0))
                ),
            }
            for tenant_id, route_id in sorted(set(old) | set(new))
        ]
        return RouteAllocationComparison(
            service_key=service_key,
            previous_allocation_run_id=previous.allocation_run_id,
            proposed_allocation_run_id=proposed.allocation_run_id,
            changes=changes,
            previous_metrics=previous.metrics,
            proposed_metrics=proposed.metrics,
        )

    def _lock_service(self, service_key: str) -> None:
        if self.session.get_bind().dialect.name == "postgresql":
            self.session.execute(
                text("SELECT pg_advisory_xact_lock(hashtext(:service_key))"),
                {"service_key": service_key},
            )

    def _map_run(self, record: RouteAllocationRunRecord) -> RouteAllocationRun:
        result_records = self.session.scalars(
            select(RouteAllocationResultRecord)
            .where(RouteAllocationResultRecord.allocation_run_id == record.id)
            .order_by(
                RouteAllocationResultRecord.tenant_id,
                RouteAllocationResultRecord.route_id,
            )
        ).all()
        allocations = [
            RouteAllocation(
                tenant_id=item.tenant_id,
                route_id=item.route_id,
                allocated_rate=item.allocated_rate,
                predicted_demand=item.predicted_demand,
                tenant_allocation_limit=item.tenant_allocation_limit,
                estimated_resource_usage=item.estimated_resource_usage,
                route_weight=item.route_weight,
                resource_cost_factor=item.resource_cost_factor,
                priority=item.priority,
                minimum_rate=item.minimum_rate,
                maximum_rate=item.maximum_rate,
                adaptive_enabled=item.adaptive_enabled,
            )
            for item in result_records
        ]
        return RouteAllocationRun(
            allocation_run_id=record.id,
            service_key=record.service_key,
            allocation_version=record.allocation_version,
            tenant_allocation_run_id=record.tenant_allocation_run_id,
            global_capacity=record.global_capacity,
            backend_resource_budget=record.backend_resource_budget,
            allocations=allocations,
            metrics=RouteAllocationMetrics.model_validate(
                record.evaluation_metrics
            ),
            created_at=record.created_at,
        )

    @staticmethod
    def _config_from_record(
        record: RouteAllocationConfigRecord,
    ) -> RouteAllocationConfig:
        return RouteAllocationConfig(
            tenant_id=record.tenant_id,
            route_id=record.route_id,
            route_weight=record.route_weight,
            route_minimum_rate=record.minimum_rate,
            route_maximum_rate=record.maximum_rate,
            resource_cost_factor=record.resource_cost_factor,
            predicted_demand=record.predicted_demand,
            priority=record.priority,
            adaptive_enabled=record.adaptive_enabled,
            current_allocation=record.current_allocation,
        )

    @staticmethod
    def _apply_config(
        record: RouteAllocationConfigRecord,
        config: RouteAllocationConfig,
        now: datetime,
    ) -> None:
        record.route_weight = config.route_weight
        record.minimum_rate = config.route_minimum_rate
        record.maximum_rate = config.route_maximum_rate
        record.resource_cost_factor = config.resource_cost_factor
        record.predicted_demand = config.predicted_demand
        record.priority = config.priority
        record.adaptive_enabled = config.adaptive_enabled
        record.current_allocation = config.current_allocation
        record.updated_at = now
