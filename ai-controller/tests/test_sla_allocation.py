from datetime import datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.route_allocation.schemas import (
    RouteAllocationConfig,
    RouteAllocationConfigList,
)
from app.route_allocation.allocation_repository import RouteAllocationRepository
from app.sla_allocation.guarantee_validator import SlaGuaranteeError
from app.sla_allocation.schemas import (
    ServiceTier,
    TenantSlaConfigInput,
    TenantSlaConfigList,
)
from app.sla_allocation.sla_allocator import allocate_sla_capacity
from app.sla_allocation.sla_service import SlaService
from app.telemetry.models import (
    Base,
    TenantSlaConfigVersionRecord,
)

NOW = datetime(2026, 11, 5, tzinfo=timezone.utc)


def sla(
    tenant_id: str,
    tier: ServiceTier = ServiceTier.BASIC,
    *,
    priority: int | None = None,
    weight: str | None = None,
    minimum: str | None = None,
    maximum: str | None = None,
    demand: str = "1000",
    adaptive: bool = True,
) -> TenantSlaConfigInput:
    return TenantSlaConfigInput(
        tenant_id=tenant_id,
        tier=tier,
        priority=priority,
        allocation_weight=Decimal(weight) if weight is not None else None,
        minimum_guaranteed_rate=(
            Decimal(minimum) if minimum is not None else None
        ),
        maximum_rate=Decimal(maximum) if maximum is not None else None,
        predicted_demand=Decimal(demand),
        adaptive_enabled=adaptive,
    )


def engine():
    database = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(database)
    return database


def test_basic_pro_enterprise_tier_defaults_and_allocation():
    configs = [
        sla("basic", ServiceTier.BASIC),
        sla("pro", ServiceTier.PRO),
        sla("enterprise", ServiceTier.ENTERPRISE),
    ]

    allocations = allocate_sla_capacity(configs, Decimal("1000"))

    assert allocations == {
        "basic": Decimal("88.235"),
        "pro": Decimal("252.941"),
        "enterprise": Decimal("658.824"),
    }
    assert sum(allocations.values()) == Decimal("1000")
    assert allocations["enterprise"] > allocations["pro"] > allocations["basic"]
    normalized_extras = (
        allocations["basic"] - Decimal("50"),
        (allocations["pro"] - Decimal("100")) / Decimal("4"),
        (allocations["enterprise"] - Decimal("200")) / Decimal("12"),
    )
    assert max(normalized_extras) - min(normalized_extras) < Decimal("0.001")


def test_guarantees_and_maximums_are_respected():
    configs = [
        sla("a", minimum="100", maximum="150", demand="1000"),
        sla("b", minimum="50", maximum="300", demand="1000"),
    ]
    allocations = allocate_sla_capacity(configs, Decimal("400"))

    assert allocations["a"] == Decimal("150.000")
    assert allocations["b"] == Decimal("250.000")
    assert all(allocations[item.tenant_id] >= item.minimum_guaranteed_rate
               for item in configs)
    assert all(allocations[item.tenant_id] <= item.maximum_rate
               for item in configs)


def test_demand_caps_redistribute_remaining_capacity():
    configs = [
        sla("basic", ServiceTier.BASIC, demand="60"),
        sla("pro", ServiceTier.PRO, demand="1000"),
        sla("enterprise", ServiceTier.ENTERPRISE, demand="1000"),
    ]
    allocations = allocate_sla_capacity(configs, Decimal("1000"))

    assert allocations["basic"] == Decimal("60")
    assert sum(allocations.values()) == Decimal("1000")
    assert allocations["pro"] <= Decimal("400")
    assert allocations["enterprise"] <= Decimal("800")


def test_impossible_guarantees_fail_without_exceeding_capacity():
    configs = [
        sla("basic", minimum="60"),
        sla("pro", minimum="60"),
    ]
    with pytest.raises(SlaGuaranteeError, match="exceed global service capacity"):
        allocate_sla_capacity(configs, Decimal("100"))


def test_equal_priority_weights_are_deterministic():
    configs = [
        sla(
            "b",
            priority=2,
            weight="2",
            minimum="10",
            maximum="100",
        ),
        sla(
            "a",
            priority=1,
            weight="4",
            minimum="10",
            maximum="100",
        ),
    ]
    first = allocate_sla_capacity(configs, Decimal("100"))
    second = allocate_sla_capacity(configs, Decimal("100"))
    assert first == second
    assert first["a"] == first["b"]


def test_sla_config_changes_are_immutable_and_run_captures_version():
    database = engine()
    with Session(database) as session:
        service = SlaService()
        first = service.replace_configs(
            "orders-service",
            TenantSlaConfigList(
                tenants=[
                    sla("basic", ServiceTier.BASIC),
                    sla("pro", ServiceTier.PRO),
                    sla("enterprise", ServiceTier.ENTERPRISE),
                ]
            ),
            session=session,
            now=NOW,
        )
        run = service.evaluate(
            "orders-service",
            Decimal("1000"),
            session=session,
            now=NOW,
        )
        updated = service.replace_configs(
            "orders-service",
            TenantSlaConfigList(
                tenants=[
                    sla("basic", ServiceTier.BASIC, weight="3"),
                ]
            ),
            session=session,
            now=NOW,
        )
        snapshots = session.scalars(
            select(TenantSlaConfigVersionRecord).where(
                TenantSlaConfigVersionRecord.tenant_id == "basic"
            ).order_by(TenantSlaConfigVersionRecord.config_version)
        ).all()
        history = service.history(
            "orders-service",
            session=session,
            limit=10,
        )

    assert first[0].config_version == 1
    assert updated[0].config_version == 2
    assert [(item.config_version, item.allocation_weight) for item in snapshots] == [
        (1, Decimal("1.000")),
        (2, Decimal("3.000")),
    ]
    assert run.allocations[0].config_version == 1
    assert history.runs[0].allocations[0].config_version == 1


def test_route_minimums_must_fit_proposed_tenant_allocation():
    database = engine()
    with Session(database) as session:
        SlaService().replace_configs(
            "orders-service",
            TenantSlaConfigList(
                tenants=[
                        sla("basic", minimum="50", maximum="150", demand="100"),
                ]
            ),
            session=session,
            now=NOW,
        )
        RouteAllocationRepository(session).replace_configs(
            "orders-service",
            RouteAllocationConfigList(
                routes=[
                    RouteAllocationConfig(
                        tenant_id="basic",
                        route_id="one",
                        route_weight=Decimal("1"),
                        route_minimum_rate=Decimal("60"),
                        route_maximum_rate=Decimal("100"),
                        resource_cost_factor=Decimal("1"),
                        predicted_demand=Decimal("100"),
                    ),
                    RouteAllocationConfig(
                        tenant_id="basic",
                        route_id="two",
                        route_weight=Decimal("1"),
                        route_minimum_rate=Decimal("60"),
                        route_maximum_rate=Decimal("100"),
                        resource_cost_factor=Decimal("1"),
                        predicted_demand=Decimal("100"),
                    ),
                ]
            ),
            now=NOW,
        )
        with pytest.raises(
            SlaGuaranteeError,
            match="Route minimums.*exceed its proposed SLA allocation",
        ):
            SlaService().evaluate(
                "orders-service",
                Decimal("500"),
                session=session,
                now=NOW,
            )


def test_compliance_is_not_claimed_without_tenant_scoped_telemetry():
    database = engine()
    with Session(database) as session:
        service = SlaService()
        service.replace_configs(
            "orders-service",
            TenantSlaConfigList(tenants=[sla("basic")]),
            session=session,
            now=NOW,
        )
        service.evaluate(
            "orders-service",
            Decimal("500"),
            session=session,
            now=NOW,
        )
        report = service.compliance("orders-service", session=session)

    assert report.tenants[0].sla_compliance == "NOT_MEASURABLE"
    assert report.tenants[0].actual_admitted_rps is None
    assert report.tenants[0].actual_throttle_ratio is None
    assert report.tenants[0].p95_latency_ms is None
    assert report.tenants[0].error_rate is None
