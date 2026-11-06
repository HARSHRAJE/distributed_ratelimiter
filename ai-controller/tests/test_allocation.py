from datetime import datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.allocation.allocation_constraints import AllocationConfigurationError
from app.allocation.allocation_repository import AllocationRepository
from app.allocation.schemas import (
    TenantAllocationConfig,
    TenantAllocationConfigList,
)
from app.allocation.weighted_allocator import weighted_water_fill
from app.telemetry.models import Base

NOW = datetime(2026, 11, 5, tzinfo=timezone.utc)


def tenant(
    tenant_id: str,
    *,
    weight: str = "1",
    priority: int = 1,
    minimum: str = "0",
    maximum: str = "1000",
    demand: str = "1000",
    current: str = "0",
    adaptive: bool = True,
) -> TenantAllocationConfig:
    return TenantAllocationConfig(
        tenant_id=tenant_id,
        tenant_priority=priority,
        weight=Decimal(weight),
        minimum_rate=Decimal(minimum),
        maximum_rate=Decimal(maximum),
        adaptive_enabled=adaptive,
        predicted_demand=Decimal(demand),
        current_allocation=Decimal(current),
    )


def database():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return engine


def test_weighted_water_filling_matches_weighted_shares():
    allocations = weighted_water_fill(
        [
            tenant("tenant-a", weight="3"),
            tenant("tenant-b", weight="2"),
            tenant("tenant-c", weight="1"),
        ],
        Decimal("1000"),
    )

    assert [item.allocation_rate for item in allocations] == [
        Decimal("500.000"),
        Decimal("333.333"),
        Decimal("166.667"),
    ]
    assert sum(item.allocation_rate for item in allocations) == Decimal("1000")


def test_minimum_and_maximum_bounds_are_respected():
    allocations = weighted_water_fill(
        [
            tenant("tenant-a", minimum="200", maximum="300"),
            tenant("tenant-b", minimum="100", maximum="500"),
        ],
        Decimal("500"),
    )

    assert [item.allocation_rate for item in allocations] == [
        Decimal("300.000"),
        Decimal("200.000"),
    ]


def test_demand_limit_redistributes_unused_capacity():
    allocations = weighted_water_fill(
        [
            tenant("tenant-a", demand="100"),
            tenant("tenant-b", demand="1000"),
        ],
        Decimal("500"),
    )

    assert [item.allocation_rate for item in allocations] == [
        Decimal("100.000"),
        Decimal("400.000"),
    ]


def test_impossible_minimums_are_rejected():
    with pytest.raises(
        AllocationConfigurationError,
        match="minimum allocations exceeds",
    ):
        weighted_water_fill(
            [
                tenant("tenant-a", minimum="300"),
                tenant("tenant-b", minimum="300"),
            ],
            Decimal("500"),
        )


def test_disabled_tenant_keeps_fixed_allocation():
    allocations = weighted_water_fill(
        [
            tenant(
                "tenant-a",
                minimum="100",
                maximum="200",
                current="150",
                adaptive=False,
            ),
            tenant("tenant-b", demand="500"),
        ],
        Decimal("500"),
    )

    assert [item.allocation_rate for item in allocations] == [
        Decimal("150"),
        Decimal("350.000"),
    ]


def test_allocations_are_deterministic_for_identical_inputs():
    tenants = [
        tenant("tenant-b", weight="2"),
        tenant("tenant-a", weight="3"),
        tenant("tenant-c", weight="1"),
    ]

    first = weighted_water_fill(tenants, Decimal("999.999"))
    second = weighted_water_fill(tenants, Decimal("999.999"))
    assert first == second
    assert sum(item.allocation_rate for item in first) <= Decimal("999.999")


def test_persisted_runs_keep_history_and_increment_per_service_version():
    engine = database()
    with Session(engine) as session:
        repository = AllocationRepository(session)
        first_configs = TenantAllocationConfigList(
            tenants=[tenant("tenant-a"), tenant("tenant-b")]
        )
        repository.save_configs("orders-service", first_configs, now=NOW)
        first = repository.evaluate(
            "orders-service",
            Decimal("100"),
            now=NOW,
        )

        updated_configs = TenantAllocationConfigList(
            tenants=[
                tenant("tenant-a", weight="3"),
                tenant("tenant-b", weight="1"),
            ]
        )
        repository.save_configs(
            "orders-service",
            updated_configs,
            now=NOW,
        )
        second = repository.evaluate(
            "orders-service",
            Decimal("100"),
            now=NOW,
        )
        history = repository.history("orders-service", limit=10)

    assert first.allocation_version == 1
    assert second.allocation_version == 2
    assert len(history) == 2
    assert history[1].allocations == first.allocations
    assert history[0].allocations[0].tenant_priority == 1
