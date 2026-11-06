from datetime import datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.allocation.allocation_repository import AllocationRepository
from app.allocation.schemas import (
    TenantAllocationConfig,
    TenantAllocationConfigList,
)
from app.route_allocation.allocation_repository import RouteAllocationRepository
from app.route_allocation.multi_route_allocator import allocate_routes
from app.route_allocation.resource_constraints import (
    RouteAllocationConstraintError,
)
from app.route_allocation.schemas import (
    RouteAllocationConfig,
    RouteAllocationConfigList,
)
from app.telemetry.models import Base

NOW = datetime(2026, 11, 5, tzinfo=timezone.utc)


def tenant(tenant_id: str, *, weight: str = "1", demand: str = "1000"):
    return TenantAllocationConfig(
        tenant_id=tenant_id,
        tenant_priority=1,
        weight=Decimal(weight),
        minimum_rate=Decimal("0"),
        maximum_rate=Decimal("1000"),
        adaptive_enabled=True,
        predicted_demand=Decimal(demand),
        current_allocation=Decimal("0"),
    )


def route(
    tenant_id: str,
    route_id: str,
    *,
    weight: str = "1",
    priority: int = 1,
    minimum: str = "0",
    maximum: str = "1000",
    cost: str = "1",
    demand: str = "1000",
    current: str = "0",
    adaptive: bool = True,
) -> RouteAllocationConfig:
    return RouteAllocationConfig(
        tenant_id=tenant_id,
        route_id=route_id,
        route_weight=Decimal(weight),
        route_minimum_rate=Decimal(minimum),
        route_maximum_rate=Decimal(maximum),
        resource_cost_factor=Decimal(cost),
        predicted_demand=Decimal(demand),
        priority=priority,
        adaptive_enabled=adaptive,
        current_allocation=Decimal(current),
    )


def db_engine():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return engine


def seed_tenant_run(session: Session, *, capacity: str = "1000"):
    AllocationRepository(session).save_configs(
        "orders-service",
        TenantAllocationConfigList(
            tenants=[tenant("tenant-a", demand=capacity)]
        ),
        now=NOW,
    )
    return AllocationRepository(session).evaluate(
        "orders-service",
        Decimal(capacity),
        now=NOW,
    )


def test_resource_aware_weights_favor_lower_cost_routes():
    allocations = allocate_routes(
        [
            route("tenant-a", "cheap", cost="1"),
            route("tenant-a", "expensive", cost="5"),
        ],
        {"tenant-a": Decimal("1000")},
        Decimal("100"),
        Decimal("100"),
    )

    cheap = allocations[("tenant-a", "cheap")]
    expensive = allocations[("tenant-a", "expensive")]
    assert cheap == Decimal("50.000")
    assert expensive == Decimal("10.000")
    assert cheap > expensive
    assert cheap + expensive <= Decimal("100")
    assert cheap + expensive * Decimal("5") <= Decimal("100")


def test_route_maximum_and_demand_caps_redistribute_capacity():
    allocations = allocate_routes(
        [
            route("tenant-a", "capped", maximum="20", demand="1000"),
            route("tenant-a", "flexible", demand="1000"),
        ],
        {"tenant-a": Decimal("100")},
        Decimal("100"),
        Decimal("1000"),
    )

    assert allocations[("tenant-a", "capped")] == Decimal("20.000")
    assert allocations[("tenant-a", "flexible")] == Decimal("80.000")


def test_route_minimums_and_tenant_limits_are_both_respected():
    allocations = allocate_routes(
        [
            route("tenant-a", "one", minimum="10"),
            route("tenant-a", "two", minimum="10"),
            route("tenant-b", "three"),
        ],
        {
            "tenant-a": Decimal("30"),
            "tenant-b": Decimal("50"),
        },
        Decimal("80"),
        Decimal("1000"),
    )

    assert allocations[("tenant-a", "one")] >= Decimal("10")
    assert allocations[("tenant-a", "two")] >= Decimal("10")
    assert (
        allocations[("tenant-a", "one")]
        + allocations[("tenant-a", "two")]
        <= Decimal("30")
    )
    assert sum(allocations.values()) <= Decimal("80")


def test_insufficient_resource_budget_for_minimums_is_rejected():
    with pytest.raises(
        RouteAllocationConstraintError,
        match="minimums exceed the backend resource budget",
    ):
        allocate_routes(
            [
                route("tenant-a", "one", minimum="10", cost="5"),
            ],
            {"tenant-a": Decimal("100")},
            Decimal("100"),
            Decimal("49"),
        )


def test_route_minimums_cannot_exceed_tenant_allocation():
    with pytest.raises(
        RouteAllocationConstraintError,
        match="exceed its tenant-wide allocation",
    ):
        allocate_routes(
            [
                route("tenant-a", "one", minimum="30"),
                route("tenant-a", "two", minimum="30"),
            ],
            {"tenant-a": Decimal("50")},
            Decimal("100"),
            Decimal("1000"),
        )


def test_deterministic_for_identical_inputs_and_respects_budgets():
    configs = [
        route("tenant-a", "b", weight="2", cost="3"),
        route("tenant-a", "a", weight="3", cost="1"),
        route("tenant-b", "c", weight="1", cost="2"),
    ]
    limits = {
        "tenant-a": Decimal("60"),
        "tenant-b": Decimal("40"),
    }
    first = allocate_routes(
        configs,
        limits,
        Decimal("100"),
        Decimal("150"),
    )
    second = allocate_routes(
        configs,
        limits,
        Decimal("100"),
        Decimal("150"),
    )

    assert first == second
    assert sum(first.values()) <= Decimal("100")
    assert sum(
        (
            first[(item.tenant_id, item.route_id)]
            * item.resource_cost_factor
            for item in configs
        ),
        Decimal(0),
    ) <= Decimal("150")
    for tenant_id, limit in limits.items():
        assert sum(
            (
                rate
                for (allocation_tenant, _), rate in first.items()
                if allocation_tenant == tenant_id
            ),
            Decimal(0),
        ) <= limit


def test_repository_stores_shadow_history_and_comparison():
    engine = db_engine()
    with Session(engine) as session:
        seed_tenant_run(session)
        repository = RouteAllocationRepository(session)
        repository.replace_configs(
            "orders-service",
            RouteAllocationConfigList(
                routes=[
                    route("tenant-a", "route-one", demand="100"),
                    route("tenant-a", "route-two", demand="100"),
                ]
            ),
            now=NOW,
        )
        first = repository.evaluate(
            "orders-service",
            Decimal("100"),
            now=NOW,
        )
        repository.replace_configs(
            "orders-service",
            RouteAllocationConfigList(
                routes=[
                    route("tenant-a", "route-one", weight="3", demand="100"),
                    route("tenant-a", "route-two", demand="100"),
                ]
            ),
            now=NOW,
        )
        second = repository.evaluate(
            "orders-service",
            Decimal("100"),
            now=NOW,
        )
        latest = repository.latest("orders-service")
        history = repository.history("orders-service", limit=10)
        comparison = repository.comparison("orders-service")

    assert first.allocation_version == 1
    assert second.allocation_version == 2
    assert latest.allocation_run_id == second.allocation_run_id
    assert len(history) == 2
    assert comparison.proposed_allocation_run_id == second.allocation_run_id
    assert comparison.changes[0].change_rate != 0
