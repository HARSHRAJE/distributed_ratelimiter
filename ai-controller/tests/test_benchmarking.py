from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.benchmarking.benchmark_repository import BenchmarkRepository
from app.benchmarking.benchmark_runner import BenchmarkRunner
from app.benchmarking.comparison_engine import ComparisonEngine
from app.benchmarking.k6_executor import K6ExecutionError, K6Executor
from app.benchmarking.scenario_manager import ScenarioManager
from app.benchmarking.schemas import (
    BenchmarkMetrics,
    BenchmarkRequest,
    BenchmarkResult,
    BenchmarkRun,
    BenchmarkScenario,
    BenchmarkSloThresholds,
    BenchmarkStrategy,
)
from app.config import Settings
from app.main import create_app
from app.telemetry.models import Base

NOW = datetime(2026, 11, 5, tzinfo=timezone.utc)


def settings() -> Settings:
    return Settings(
        prometheus_url="http://prometheus:9090",
        service_keys=("orders-service",),
        collection_interval_seconds=15,
        stale_after_seconds=60,
        aggregation_window_seconds=300,
        prometheus_timeout_seconds=5,
        api_key="i" * 32,
        db_host="localhost",
        db_port=5432,
        db_name="test",
        db_username="test",
        db_password="test",
        benchmark_git_commit="abc123",
        benchmark_target_url="http://localhost:8080",
        benchmark_tenant_tokens=("token-0", "token-1", "token-2", "token-3", "token-4"),
    )


def thresholds() -> BenchmarkSloThresholds:
    return BenchmarkSloThresholds(
        max_p95_latency_ms=200,
        max_p99_latency_ms=400,
        max_backend_error_ratio=0.01,
        max_rejection_ratio=0.1,
        max_sla_violation_count=0,
        minimum_fairness_index=0.9,
        max_cpu_usage_percent=80,
        max_memory_usage_percent=90,
        max_redis_latency_ms=25,
        max_redis_error_count=0,
        max_dropped_iterations=0,
        minimum_successful_rps=5,
    )


def request_model(**overrides) -> BenchmarkRequest:
    values = {
        "service_key": "orders-service",
        "environment_id": "local-test-stack",
        "strategies": list(BenchmarkStrategy),
        "scenario": BenchmarkScenario.STEADY_TRAFFIC,
        "duration_seconds": 10,
        "warmup_seconds": 0,
        "tenant_count": 5,
        "start_rps": 10,
        "peak_rps": 20,
        "strategy_config_versions": {
            strategy.value: f"version-{strategy.value}"
            for strategy in BenchmarkStrategy
        },
        "slo_thresholds": thresholds(),
        "isolated_test_environment_confirmed": True,
    }
    values.update(overrides)
    return BenchmarkRequest(**values)


def database():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return engine


def test_scenario_manager_profiles_are_bounded_and_distinct():
    steady = ScenarioManager.build(
        BenchmarkScenario.STEADY_TRAFFIC,
        duration_seconds=60,
        start_rps=10,
        peak_rps=100,
    )
    spike = ScenarioManager.build(
        BenchmarkScenario.SUDDEN_SPIKE,
        duration_seconds=60,
        start_rps=10,
        peak_rps=100,
    )
    ramp = ScenarioManager.build(
        BenchmarkScenario.GRADUAL_RAMP,
        duration_seconds=60,
        start_rps=10,
        peak_rps=100,
    )
    burst = ScenarioManager.build(
        BenchmarkScenario.BURST_TRAFFIC,
        duration_seconds=60,
        start_rps=10,
        peak_rps=100,
    )

    assert steady.stages == [{"duration": 60, "target": 10}]
    assert 100 in [stage["target"] for stage in spike.stages]
    assert spike.stages[-1]["target"] == 10
    assert spike.recovery_start_seconds is not None
    assert ramp.stages == [{"duration": 60, "target": 100}]
    assert sum(int(stage["duration"]) for stage in burst.stages) == 60
    assert all(int(stage["duration"]) <= 15 for stage in burst.stages)


def test_benchmark_request_requires_isolation_versions_and_actual_slos():
    with pytest.raises(ValueError, match="isolated_test_environment"):
        request_model(isolated_test_environment_confirmed=False)
    with pytest.raises(ValueError, match="strategy_config_versions"):
        request_model(strategy_config_versions={})
    with pytest.raises(ValueError, match="fault_injection_confirmed"):
        request_model(
            scenario=BenchmarkScenario.REDIS_FAILURE,
            fault_injection_confirmed=False,
        )


def test_k6_summary_keeps_429_separate_from_backend_5xx():
    summary = {
        "metrics": {
            "http_reqs": {"values": {"count": 100, "rate": 10}},
            "dropped_iterations": {"values": {"count": 0}},
            "http_req_duration": {
                "values": {"med": 5, "p(95)": 10, "p(99)": 20}
            },
            "benchmark_accepted_latency_ms": {
                "values": {"med": 5, "p(95)": 10, "p(99)": 20}
            },
            "benchmark_backend_latency_ms": {
                "values": {"p(95)": 9}
            },
            "benchmark_rate_limited_requests": {"values": {"count": 10}},
            "benchmark_backend_errors": {"values": {"count": 5}},
            "benchmark_accepted_requests": {"values": {"count": 90}},
            "benchmark_successful_requests": {"values": {"count": 85}},
            "benchmark_strategy_mismatches": {"values": {"count": 0}},
            "benchmark_tenant_demand{tenant_id:benchmark-tenant-0}": {
                "values": {"count": 60}
            },
            "benchmark_tenant_accepted{tenant_id:benchmark-tenant-0}": {
                "values": {"count": 45}
            },
            "benchmark_tenant_demand{tenant_id:benchmark-tenant-1}": {
                "values": {"count": 40}
            },
            "benchmark_tenant_accepted{tenant_id:benchmark-tenant-1}": {
                "values": {"count": 40}
            },
        }
    }
    metrics = K6Executor._metrics_from_summary(summary, 10)

    assert metrics.incoming_rps == 10
    assert metrics.accepted_rps == 9
    assert metrics.successful_rps == 8.5
    assert metrics.rejection_ratio == 0.1
    assert metrics.backend_error_ratio == pytest.approx(5 / 90)
    assert metrics.p50_latency_ms == 5
    assert metrics.backend_p95_latency_ms == 9
    assert metrics.fairness_index is not None
    assert metrics.tenant_fairness_details["benchmark-tenant-0"] == {
        "demand_rps": 6,
        "accepted_rps": 4.5,
        "demand_fulfillment_ratio": 0.75,
    }


def test_k6_summary_fails_when_strategy_is_not_confirmed():
    summary = {
        "metrics": {
            "http_reqs": {"values": {"count": 1, "rate": 1}},
            "benchmark_strategy_mismatches": {"values": {"count": 1}},
        }
    }
    with pytest.raises(K6ExecutionError, match="did not confirm"):
        K6Executor._metrics_from_summary(summary, 10)


def test_k6_executor_rejects_non_allowlisted_target():
    executor = K6Executor(
        binary="k6",
        target_url="https://example.com/",
        allowed_hosts=("localhost:8080",),
    )
    with pytest.raises(
        K6ExecutionError,
        match="host and port are not in the local test allowlist",
    ):
        executor._validate_target()


def test_benchmark_repository_queues_all_strategies_and_rotates_order():
    engine = database()
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as session:
        batch_id, runs = BenchmarkRepository(session).enqueue(
            request_model(),
            git_commit="abc123",
            k6_script_version="1",
            route_paths=("/",),
            now=NOW,
        )
        claimed = BenchmarkRepository(session).claim_next(now=NOW)

    assert len(runs) == 3
    assert all(item.batch_id == batch_id for item in runs)
    assert sorted(item.execution_order for item in runs) == [0, 1, 2]
    assert claimed is not None
    assert claimed.status == "RUNNING"
    assert claimed.slo_thresholds["max_p95_latency_ms"] == 200


@pytest.mark.asyncio
async def test_worker_persists_result_without_running_inside_http():
    engine = database()
    factory = sessionmaker(bind=engine, expire_on_commit=False)

    class FakeExecutor:
        async def execute(self, run):
            return BenchmarkMetrics(
                incoming_rps=10,
                accepted_rps=9,
                successful_rps=9,
                p50_latency_ms=5,
                p95_latency_ms=10,
                p99_latency_ms=20,
                rejection_ratio=0.1,
                backend_error_ratio=0,
            )

    class FakeCollector:
        async def collect(self, run, metrics, *, session):
            return metrics

    with factory() as session:
        BenchmarkRepository(session).enqueue(
            request_model(),
            git_commit="abc123",
            k6_script_version="1",
            route_paths=("/",),
            now=NOW,
        )
    runner = BenchmarkRunner(
        session_factory=factory,
        settings=settings(),
        executor=FakeExecutor(),
        metrics_collector=FakeCollector(),
    )

    run_id = await runner.run_once()

    assert run_id is not None
    with factory() as session:
        details = BenchmarkRepository(session).get(run_id)
        result = BenchmarkRepository(session).result(run_id)
    assert details.status == "COMPLETED", details.error
    assert result.incoming_rps == Decimal("10.000")
    assert result.backend_error_ratio == Decimal("0.000000")


def test_comparison_reports_slo_failures_and_only_supported_improvements():
    batch = uuid4()
    threshold = thresholds()
    runs = []
    for strategy, p95, successful in (
        (BenchmarkStrategy.STATIC, 100, 8),
        (BenchmarkStrategy.RULE_BASED, 150, 9),
        (BenchmarkStrategy.AI_SLA_ADAPTIVE, 250, 10),
    ):
        run = BenchmarkRun(
            id=uuid4(),
            batch_id=batch,
            execution_order=len(runs),
            strategy=strategy,
            scenario=BenchmarkScenario.STEADY_TRAFFIC,
            service_key="orders-service",
            environment_id="local-test-stack",
            status="COMPLETED",
            config_version=f"version-{strategy.value}",
            git_commit="abc123",
            k6_script_version="1",
            started_at=NOW,
            completed_at=NOW + timedelta(seconds=10),
            duration_seconds=10,
            warmup_seconds=0,
            tenant_count=5,
            start_rps=10,
            peak_rps=20,
            fault_injection_confirmed=False,
            slo_thresholds=threshold,
            workload_parameters={
                "duration_seconds": 10,
                "warmup_seconds": 0,
                "tenant_count": 5,
                "start_rps": 10,
                "peak_rps": 20,
                "route_paths": ["/"],
            },
            error=None,
            created_at=NOW,
        )
        result = BenchmarkResult(
            id=uuid4(),
            run_id=run.id,
            incoming_rps=10,
            accepted_rps=10,
            successful_rps=successful,
            p50_latency_ms=5,
            p95_latency_ms=p95,
            p99_latency_ms=p95 * 2,
            backend_p95_latency_ms=p95 - 5,
            rejection_ratio=0,
            backend_error_ratio=0,
            cpu_usage=50,
            gateway_cpu_usage=45,
            memory_usage=60,
            gateway_memory_usage=55,
            redis_latency_ms=1,
            sla_violation_count=0,
            fairness_index=0.95,
            fairness_basis="request_admission_by_tenant",
            tenant_fairness_details=None,
            allocation_proposal_fairness_index=None,
            policy_changes=0,
            stabilization_time_seconds=None,
            redis_commands_per_second=10,
            redis_connection_count=5,
            redis_memory_bytes=1000,
            redis_error_count=0,
            redis_hot_key_observation=None,
            forecast_mae=None,
            forecast_wape=None,
            recommendation_generation_ms=None,
            policy_application_ms=None,
            propagation_delay_ms=None,
            oscillation_frequency=0,
            prometheus_query_reference=None,
            metrics_collection_errors=[],
            dropped_iterations=0,
            created_at=NOW,
        )
        runs.append((run, result))

    comparison = ComparisonEngine().compare(
        service_key="orders-service",
        scenario=BenchmarkScenario.STEADY_TRAFFIC,
        environment_id="local-test-stack",
        runs=runs,
    )

    assert comparison.slo_pass["STATIC"] is True
    assert comparison.slo_pass["RULE_BASED"] is True
    assert comparison.slo_pass["AI_SLA_ADAPTIVE"] is False
    assert any("p95_latency_ms" in item for item in comparison.slo_violations[
        "AI_SLA_ADAPTIVE"
    ])
    assert not comparison.improvements_vs_static


def test_benchmark_api_queues_batch_and_returns_status():
    engine = database()
    client = TestClient(create_app(settings(), engine))
    payload = request_model().model_dump(mode="json")

    response = client.post(
        "/api/v1/benchmarks/run",
        headers={"X-Internal-API-Key": "i" * 32},
        json=payload,
    )

    assert response.status_code == 202
    assert len(response.json()["run_ids"]) == 3
    run_id = response.json()["run_ids"][0]
    status = client.get(
        f"/api/v1/benchmarks/{run_id}",
        headers={"X-Internal-API-Key": "i" * 32},
    )
    assert status.status_code == 200
    assert status.json()["status"] == "QUEUED"
