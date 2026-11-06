import asyncio

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.chaos.experiment_models import ChaosExperimentRecord
from app.chaos.experiment_repository import ChaosExperimentRepository
from app.chaos.experiment_runner import ChaosExperimentRunner
from app.chaos.fault_injector import (
    ChaosSafetyError,
    FaultInjector,
    FaultObservation,
)
from app.chaos.safety_validator import SafetyValidator
from app.chaos.schemas import ChaosExperimentRequest
from app.config import Settings
from app.main import create_app
from app.telemetry.models import Base

INTERNAL_KEY = "i" * 32
ADMIN_KEY = "a" * 32
ORIGINAL_ASYNC_SLEEP = asyncio.sleep


def settings(**overrides) -> Settings:
    values = {
        "prometheus_url": "http://prometheus:9090",
        "service_keys": ("orders-service",),
        "collection_interval_seconds": 15,
        "stale_after_seconds": 60,
        "aggregation_window_seconds": 300,
        "prometheus_timeout_seconds": 5,
        "api_key": INTERNAL_KEY,
        "db_host": "localhost",
        "db_port": 5432,
        "db_name": "test",
        "db_username": "test",
        "db_password": "test",
        "administrator_api_key": ADMIN_KEY,
        "chaos_enabled": True,
        "chaos_test_environment_id": "local-chaos-test",
    }
    values.update(overrides)
    return Settings(**values)


def database():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return engine


def request_body(**overrides) -> dict:
    values = {
        "experiment_code": "CH-01",
        "test_environment_id": "local-chaos-test",
        "service_key": "orders-service",
        "fault_duration_seconds": 1,
        "confirm_isolated_environment": True,
        "confirm_gateway_traffic_is_test_traffic": True,
        "operator_note": "local test",
    }
    values.update(overrides)
    return values


def test_chaos_enqueue_requires_internal_and_admin_keys():
    engine = database()
    client = TestClient(create_app(settings(), engine))

    response = client.post(
        "/api/v1/chaos/experiments",
        json=request_body(),
        headers={"X-Internal-API-Key": INTERNAL_KEY},
    )

    assert response.status_code == 401


def test_chaos_enqueue_is_explicitly_authorized_and_queued():
    engine = database()
    client = TestClient(create_app(settings(), engine))

    response = client.post(
        "/api/v1/chaos/experiments",
        json=request_body(),
        headers={
            "X-Internal-API-Key": INTERNAL_KEY,
            "X-Admin-API-Key": ADMIN_KEY,
        },
    )

    assert response.status_code == 202
    assert response.json()["experiment"]["status"] == "QUEUED"
    assert response.json()["experiment"]["experiment_code"] == "CH-01"


def test_chaos_rejects_disabled_or_unimplemented_scenarios():
    engine = database()
    client = TestClient(create_app(settings(chaos_enabled=False), engine))
    enabled_client = TestClient(create_app(settings(), engine))
    headers = {
        "X-Internal-API-Key": INTERNAL_KEY,
        "X-Admin-API-Key": ADMIN_KEY,
    }
    disabled = client.post(
        "/api/v1/chaos/experiments",
        json=request_body(),
        headers=headers,
    )
    unsupported = enabled_client.post(
        "/api/v1/chaos/experiments",
        json=request_body(experiment_code="CH-02"),
        headers={
            **headers,
            "X-Internal-API-Key": INTERNAL_KEY,
        },
    )

    assert disabled.status_code == 422
    assert unsupported.status_code == 501
    assert "not implemented" in unsupported.json()["detail"]


def test_chaos_requires_both_operator_confirmations():
    engine = database()
    client = TestClient(create_app(settings(), engine))

    response = client.post(
        "/api/v1/chaos/experiments",
        json=request_body(confirm_isolated_environment=False),
        headers={
            "X-Internal-API-Key": INTERNAL_KEY,
            "X-Admin-API-Key": ADMIN_KEY,
        },
    )

    assert response.status_code == 422


def test_fault_injector_requires_local_docker_endpoint(monkeypatch):
    injector = FaultInjector(settings())
    monkeypatch.delenv("DOCKER_HOST", raising=False)

    async def docker(*arguments):
        if arguments == ("context", "show"):
            return "desktop-linux"
        return '"npipe:////./pipe/dockerDesktopLinuxEngine"'

    async def compose(*arguments, **kwargs):
        return '{"services":{"redis":{"image":"redis:7.4"}}}'

    monkeypatch.setattr(injector, "_docker", docker)
    monkeypatch.setattr(injector, "_compose", compose)

    asyncio.run(injector._validate_compose_service())


def test_fault_injector_rejects_remote_docker_endpoint(monkeypatch):
    injector = FaultInjector(settings())
    monkeypatch.delenv("DOCKER_HOST", raising=False)

    async def docker(*arguments):
        if arguments == ("context", "show"):
            return "default"
        return '"tcp://remote.example:2376"'

    monkeypatch.setattr(injector, "_docker", docker)

    with pytest.raises(ChaosSafetyError, match="local named-pipe or Unix-socket"):
        asyncio.run(injector._validate_compose_service())


def test_safety_validator_does_not_claim_unmeasured_policy_consistency():
    assessment = SafetyValidator().assess(
        fault_observations=[{"status_code": 503}],
        recovery_observations=[{"status_code": 200}],
    )

    assert assessment.policy_consistency is False
    assert assessment.checks["policy_version_did_not_regress"] is None
    assert assessment.checks["disabled_policy_was_not_resurrected"] is None
    assert assessment.safety_violations == 0


def test_safety_validator_flags_non_503_during_redis_outage():
    assessment = SafetyValidator().assess(
        fault_observations=[{"status_code": 200}],
        recovery_observations=[{"status_code": 200}],
    )

    assert assessment.checks["fail_closed_during_redis_outage"] is False
    assert assessment.safety_violations == 1


def _queued_request() -> ChaosExperimentRequest:
    return ChaosExperimentRequest(**request_body())


def test_runner_persists_results_and_keeps_unverified_policy_false():
    engine = database()
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as session:
        experiment = ChaosExperimentRepository(session).enqueue(
            _queued_request(),
            fault_duration_seconds=1,
        )
        experiment_id = experiment.id

    class FakeInjector:
        async def inject_redis_unavailable(self, *, duration_seconds):
            assert duration_seconds == 1
            return FaultObservation(
                fault_probes=[
                    {"status_code": 503, "latency_ms": 1.0},
                    {"status_code": 503, "latency_ms": 2.0},
                ],
                recovery_probe={"status_code": 200, "latency_ms": 1.0},
                recovery_time_ms=12,
                redis_restart_confirmed=True,
                compose_events=["Stopped Redis", "Started Redis"],
            )

    runner = ChaosExperimentRunner(
        session_factory=factory,
        settings=settings(),
        fault_injector=FakeInjector(),
    )
    assert asyncio.run(runner.run_once()) == experiment_id
    with factory() as session:
        record = session.get(ChaosExperimentRecord, experiment_id)
        result = ChaosExperimentRepository(session).result(experiment_id)

    assert record is not None
    assert record.status == "COMPLETED"
    assert result is not None
    assert result.requests_sent == 3
    assert result.gateway_errors == 2
    assert result.recovery_success is True
    assert result.policy_consistency is False
    assert result.details["policy_consistency_verified"] is False


def test_runner_marks_execution_failure_without_exposing_process_output():
    engine = database()
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as session:
        experiment = ChaosExperimentRepository(session).enqueue(
            _queued_request(),
            fault_duration_seconds=1,
        )
        experiment_id = experiment.id

    class FailingInjector:
        async def inject_redis_unavailable(self, *, duration_seconds):
            raise ChaosSafetyError("sensitive process output")

    runner = ChaosExperimentRunner(
        session_factory=factory,
        settings=settings(),
        fault_injector=FailingInjector(),
    )
    assert asyncio.run(runner.run_once()) == experiment_id
    with factory() as session:
        record = session.get(ChaosExperimentRecord, experiment_id)

    assert record is not None
    assert record.status == "FAILED"
    assert "sensitive process output" not in record.error


def test_fault_injector_always_tries_fixed_redis_restart(monkeypatch):
    injector = FaultInjector(settings())
    calls = []

    async def compose(*arguments, **kwargs):
        calls.append(arguments)
        return ""

    async def probe():
        return {"status_code": 503, "latency_ms": 1.0}

    async def recovery(restart_started):
        return None, None

    monkeypatch.setattr(injector, "_validate_local_environment", lambda: None)
    monkeypatch.setattr(
        injector,
        "_validate_compose_service",
        _async_noop,
    )
    monkeypatch.setattr(injector, "_preflight_probe", _async_noop)
    monkeypatch.setattr(injector, "_compose", compose)
    monkeypatch.setattr(injector, "_probe", probe)
    monkeypatch.setattr(injector, "_wait_for_recovery", recovery)
    monkeypatch.setattr("app.chaos.fault_injector.asyncio.sleep", _fast_sleep)

    observation = asyncio.run(
        injector.inject_redis_unavailable(duration_seconds=1)
    )

    assert calls[0] == ("stop", "redis")
    assert calls[-1] == ("start", "redis")
    assert observation.redis_restart_confirmed is False
    assert observation.recovery_probe is None


def test_fault_injector_restarts_redis_when_probe_raises(monkeypatch):
    injector = FaultInjector(settings())
    calls = []

    async def compose(*arguments, **kwargs):
        calls.append(arguments)
        return ""

    async def failing_probe():
        raise RuntimeError("probe failed")

    async def recovery(restart_started):
        return None, None

    monkeypatch.setattr(injector, "_validate_local_environment", lambda: None)
    monkeypatch.setattr(
        injector,
        "_validate_compose_service",
        _async_noop,
    )
    monkeypatch.setattr(injector, "_preflight_probe", _async_noop)
    monkeypatch.setattr(injector, "_compose", compose)
    monkeypatch.setattr(injector, "_probe", failing_probe)
    monkeypatch.setattr(injector, "_wait_for_recovery", recovery)

    with pytest.raises(RuntimeError, match="probe failed"):
        asyncio.run(injector.inject_redis_unavailable(duration_seconds=1))

    assert calls == [("stop", "redis"), ("start", "redis")]


def test_fault_injector_restarts_redis_after_ambiguous_stop_failure(monkeypatch):
    injector = FaultInjector(settings())
    calls = []

    async def compose(*arguments, **kwargs):
        calls.append(arguments)
        if arguments == ("stop", "redis"):
            raise RuntimeError("stop command timed out")
        return ""

    async def recovery(restart_started):
        return None, None

    monkeypatch.setattr(injector, "_validate_local_environment", lambda: None)
    monkeypatch.setattr(injector, "_validate_compose_service", _async_noop)
    monkeypatch.setattr(injector, "_preflight_probe", _async_noop)
    monkeypatch.setattr(injector, "_compose", compose)
    monkeypatch.setattr(injector, "_wait_for_recovery", recovery)

    with pytest.raises(RuntimeError, match="stop command timed out"):
        asyncio.run(injector.inject_redis_unavailable(duration_seconds=1))

    assert calls == [("stop", "redis"), ("start", "redis")]


async def _async_noop(*args, **kwargs):
    return None


async def _fast_sleep(seconds):
    await ORIGINAL_ASYNC_SLEEP(0)
