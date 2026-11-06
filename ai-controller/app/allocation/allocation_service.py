from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy.orm import Session

from app.allocation.allocation_repository import AllocationRepository
from app.allocation.schemas import (
    AllocationHistory,
    AllocationRun,
    TenantAllocationConfig,
    TenantAllocationConfigList,
)


class AllocationService:
    def save_configs(
        self,
        service_key: str,
        configs: TenantAllocationConfigList,
        *,
        session: Session,
        now: datetime | None = None,
    ) -> list[TenantAllocationConfig]:
        records = AllocationRepository(session).save_configs(
            service_key,
            configs,
            now=now or datetime.now(timezone.utc),
        )
        return [
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
            for record in records
        ]

    def get_configs(
        self,
        service_key: str,
        *,
        session: Session,
    ) -> list[TenantAllocationConfig]:
        return [
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
            for record in AllocationRepository(session).configs(service_key)
        ]

    def evaluate(
        self,
        service_key: str,
        global_capacity_rps: Decimal,
        *,
        session: Session,
        now: datetime | None = None,
    ) -> AllocationRun:
        return AllocationRepository(session).evaluate(
            service_key,
            global_capacity_rps,
            now=now or datetime.now(timezone.utc),
        )

    @staticmethod
    def latest(
        service_key: str,
        *,
        session: Session,
    ) -> AllocationRun | None:
        return AllocationRepository(session).latest(service_key)

    @staticmethod
    def history(
        service_key: str,
        *,
        session: Session,
        limit: int,
    ) -> AllocationHistory:
        return AllocationHistory(
            service_key=service_key,
            runs=AllocationRepository(session).history(
                service_key,
                limit=limit,
            ),
        )
