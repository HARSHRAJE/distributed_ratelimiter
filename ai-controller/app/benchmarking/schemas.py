from datetime import datetime
from enum import Enum
from uuid import UUID

from pydantic import BaseModel, Field, model_validator


class BenchmarkStrategy(str, Enum):
    STATIC = "STATIC"
    RULE_BASED = "RULE_BASED"
    AI_SLA_ADAPTIVE = "AI_SLA_ADAPTIVE"


class BenchmarkScenario(str, Enum):
    STEADY_TRAFFIC = "STEADY_TRAFFIC"
    SUDDEN_SPIKE = "SUDDEN_SPIKE"
    GRADUAL_RAMP = "GRADUAL_RAMP"
    BURST_TRAFFIC = "BURST_TRAFFIC"
    TENANT_HOTSPOT = "TENANT_HOTSPOT"
    ROUTE_IMBALANCE = "ROUTE_IMBALANCE"
    BACKEND_DEGRADATION = "BACKEND_DEGRADATION"
    REDIS_FAILURE = "REDIS_FAILURE"
    CONTROLLER_FAILURE = "CONTROLLER_FAILURE"
    POLICY_SYNC_DELAY = "POLICY_SYNC_DELAY"


class CapacityProfile(str, Enum):
    BASELINE = "BASELINE"
    LOAD = "LOAD"
    STRESS = "STRESS"
    SPIKE = "SPIKE"
    SOAK = "SOAK"
    RECOVERY = "RECOVERY"


FAULT_SCENARIOS = {
    BenchmarkScenario.BACKEND_DEGRADATION,
    BenchmarkScenario.REDIS_FAILURE,
    BenchmarkScenario.CONTROLLER_FAILURE,
    BenchmarkScenario.POLICY_SYNC_DELAY,
}


class BenchmarkSloThresholds(BaseModel):
    max_p95_latency_ms: float = Field(gt=0, le=60000)
    max_p99_latency_ms: float = Field(gt=0, le=60000)
    max_backend_error_ratio: float = Field(ge=0, le=1)
    max_rejection_ratio: float = Field(ge=0, le=1)
    max_sla_violation_count: int = Field(ge=0, le=1000000)
    minimum_fairness_index: float = Field(ge=0, le=1)
    max_cpu_usage_percent: float = Field(gt=0, le=100)
    max_memory_usage_percent: float = Field(gt=0, le=100)
    max_redis_latency_ms: float = Field(gt=0, le=60000)
    max_redis_error_count: int = Field(ge=0, le=1000000)
    max_dropped_iterations: int = Field(ge=0, le=1000000)
    minimum_successful_rps: float = Field(ge=0, le=1000000)


class BenchmarkRequest(BaseModel):
    service_key: str = Field(min_length=1, max_length=100)
    environment_id: str = Field(
        min_length=1,
        max_length=100,
        pattern=r"^[A-Za-z0-9._-]+$",
    )
    strategies: list[BenchmarkStrategy] = Field(min_length=1, max_length=3)
    scenario: BenchmarkScenario
    duration_seconds: int = Field(default=60, ge=10, le=14400)
    capacity_profile: CapacityProfile | None = None
    warmup_seconds: int = Field(default=10, ge=0, le=600)
    tenant_count: int = Field(default=10, ge=1, le=1000)
    start_rps: int = Field(default=10, ge=1, le=1000)
    peak_rps: int = Field(default=100, ge=1, le=1000)
    strategy_config_versions: dict[str, str]
    slo_thresholds: BenchmarkSloThresholds
    isolated_test_environment_confirmed: bool = False
    fault_injection_confirmed: bool = False

    @model_validator(mode="after")
    def validate_request(self):
        if len(set(self.strategies)) != len(self.strategies):
            raise ValueError("strategies must not contain duplicates")
        if set(self.strategies) != set(BenchmarkStrategy):
            raise ValueError(
                "Each benchmark batch must include STATIC, RULE_BASED, "
                "and AI_SLA_ADAPTIVE"
            )
        if set(self.strategy_config_versions) != {
            strategy.value for strategy in self.strategies
        }:
            raise ValueError(
                "strategy_config_versions must identify every strategy"
            )
        if self.peak_rps < self.start_rps:
            raise ValueError("peak_rps must be at least start_rps")
        if self.capacity_profile is not None:
            expected_durations = {
                CapacityProfile.BASELINE: {300},
                CapacityProfile.LOAD: {600},
                CapacityProfile.SPIKE: {300},
                CapacityProfile.RECOVERY: {600},
            }
            if (
                self.capacity_profile in expected_durations
                and self.duration_seconds
                not in expected_durations[self.capacity_profile]
            ):
                expected = next(iter(
                    expected_durations[self.capacity_profile]
                ))
                raise ValueError(
                    f"{self.capacity_profile.value} profile duration must be "
                    f"{expected} seconds"
                )
            if (
                self.capacity_profile == CapacityProfile.SOAK
                and not 3600 <= self.duration_seconds <= 14400
            ):
                raise ValueError(
                    "SOAK profile duration must be between 3600 and "
                    "14400 seconds"
                )
            if (
                self.capacity_profile == CapacityProfile.STRESS
                and self.duration_seconds < 60
            ):
                raise ValueError(
                    "STRESS profile duration must be at least 60 seconds"
                )
        if not self.isolated_test_environment_confirmed:
            raise ValueError(
                "isolated_test_environment_confirmed must be true"
            )
        if (
            self.scenario in FAULT_SCENARIOS
            and not self.fault_injection_confirmed
        ):
            raise ValueError(
                "Fault scenarios require fault_injection_confirmed=true; "
                "this service does not inject faults"
            )
        for strategy, version in self.strategy_config_versions.items():
            if strategy not in {item.value for item in BenchmarkStrategy}:
                raise ValueError(f"Unknown strategy config key: {strategy}")
            if not version.strip() or len(version) > 200:
                raise ValueError("Strategy config versions must be non-empty")
        return self


class BenchmarkSubmission(BaseModel):
    batch_id: UUID
    run_ids: list[UUID]
    status: str


class BenchmarkRun(BaseModel):
    id: UUID
    batch_id: UUID
    execution_order: int
    strategy: BenchmarkStrategy
    scenario: BenchmarkScenario
    service_key: str
    environment_id: str
    status: str
    config_version: str
    git_commit: str
    k6_script_version: str
    started_at: datetime | None
    completed_at: datetime | None
    duration_seconds: int
    warmup_seconds: int
    tenant_count: int
    start_rps: int
    peak_rps: int
    fault_injection_confirmed: bool
    slo_thresholds: BenchmarkSloThresholds
    workload_parameters: dict[str, object]
    error: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class BenchmarkResult(BaseModel):
    id: UUID
    run_id: UUID
    incoming_rps: float | None
    accepted_rps: float | None
    successful_rps: float | None
    p50_latency_ms: float | None
    p95_latency_ms: float | None
    p99_latency_ms: float | None
    backend_p95_latency_ms: float | None
    rejection_ratio: float | None
    backend_error_ratio: float | None
    cpu_usage: float | None
    gateway_cpu_usage: float | None
    memory_usage: float | None
    gateway_memory_usage: float | None
    redis_latency_ms: float | None
    sla_violation_count: int | None
    fairness_index: float | None
    fairness_basis: str | None
    tenant_fairness_details: dict[str, dict[str, float]] | None
    allocation_proposal_fairness_index: float | None
    policy_changes: int | None
    stabilization_time_seconds: float | None
    redis_commands_per_second: float | None
    redis_connection_count: int | None
    redis_memory_bytes: int | None
    redis_error_count: int | None
    redis_hot_key_observation: str | None
    forecast_mae: float | None
    forecast_wape: float | None
    recommendation_generation_ms: float | None
    policy_application_ms: float | None
    propagation_delay_ms: float | None
    oscillation_frequency: float | None
    prometheus_query_reference: str | None
    metrics_collection_errors: list[str]
    dropped_iterations: int | None
    created_at: datetime

    model_config = {"from_attributes": True}


class BenchmarkRunDetails(BaseModel):
    run: BenchmarkRun
    result: BenchmarkResult | None


class BenchmarkHistory(BaseModel):
    runs: list[BenchmarkRun]


class StrategyComparison(BaseModel):
    strategy: BenchmarkStrategy
    sample_count: int
    means: dict[str, float | None]
    standard_deviations: dict[str, float | None]


class BenchmarkComparison(BaseModel):
    service_key: str
    scenario: BenchmarkScenario
    environment_id: str | None
    slo_thresholds: BenchmarkSloThresholds | None
    batch_ids: list[UUID]
    strategies: list[StrategyComparison]
    regressions_vs_static: list[str]
    improvements_vs_static: list[str]
    slo_violations: dict[str, list[str]]
    slo_pass: dict[str, bool]
    metrics_collection_errors: dict[str, list[str]]
    report: str


class BenchmarkMetrics(BaseModel):
    incoming_rps: float | None = None
    accepted_rps: float | None = None
    successful_rps: float | None = None
    p50_latency_ms: float | None = None
    p95_latency_ms: float | None = None
    p99_latency_ms: float | None = None
    backend_p95_latency_ms: float | None = None
    rejection_ratio: float | None = None
    backend_error_ratio: float | None = None
    cpu_usage: float | None = None
    gateway_cpu_usage: float | None = None
    memory_usage: float | None = None
    gateway_memory_usage: float | None = None
    redis_latency_ms: float | None = None
    sla_violation_count: int | None = None
    fairness_index: float | None = None
    fairness_basis: str | None = None
    tenant_fairness_details: dict[str, dict[str, float]] | None = None
    allocation_proposal_fairness_index: float | None = None
    policy_changes: int | None = None
    stabilization_time_seconds: float | None = None
    redis_commands_per_second: float | None = None
    redis_connection_count: int | None = None
    redis_memory_bytes: int | None = None
    redis_error_count: int | None = None
    redis_hot_key_observation: str | None = None
    forecast_mae: float | None = None
    forecast_wape: float | None = None
    recommendation_generation_ms: float | None = None
    policy_application_ms: float | None = None
    propagation_delay_ms: float | None = None
    oscillation_frequency: float | None = None
    prometheus_query_reference: str | None = None
    metrics_collection_errors: list[str] = Field(default_factory=list)
    dropped_iterations: int | None = None
