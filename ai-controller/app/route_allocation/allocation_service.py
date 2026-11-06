from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy.orm import Session

from app.route_allocation.allocation_repository import RouteAllocationRepository
from app.route_allocation.schemas import (
    RouteAllocationComparison,
    RouteAllocationConfig,
    RouteAllocationConfigList,
    RouteAllocationHistory,
    RouteAllocationRun,
)


class RouteAllocationService:
    def replace_configs(
        self,
        service_key: str,
        configs: RouteAllocationConfigList,
        *,
        session: Session,
        now: datetime | None = None,
    ) -> list[RouteAllocationConfig]:
        return RouteAllocationRepository(session).replace_configs(
            service_key,
            configs,
            now=now or datetime.now(timezone.utc),
        )

    def evaluate(
        self,
        service_key: str,
        backend_resource_budget: Decimal,
        *,
        session: Session,
        now: datetime | None = None,
    ) -> RouteAllocationRun:
        return RouteAllocationRepository(session).evaluate(
            service_key,
            backend_resource_budget,
            now=now or datetime.now(timezone.utc),
        )

    @staticmethod
    def latest(
        service_key: str,
        *,
        session: Session,
    ) -> RouteAllocationRun | None:
        return RouteAllocationRepository(session).latest(service_key)

    @staticmethod
    def history(
        service_key: str,
        *,
        session: Session,
        limit: int,
    ) -> RouteAllocationHistory:
        return RouteAllocationHistory(
            service_key=service_key,
            runs=RouteAllocationRepository(session).history(
                service_key,
                limit=limit,
            ),
        )

    @staticmethod
    def comparison(
        service_key: str,
        *,
        session: Session,
    ) -> RouteAllocationComparison | None:
        return RouteAllocationRepository(session).comparison(service_key)
