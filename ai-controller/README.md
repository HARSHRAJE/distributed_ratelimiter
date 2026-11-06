# AI Controller telemetry service

This Python 3.12+ project reads service-level metrics from Prometheus, stores
raw samples and separate rolling aggregates in PostgreSQL, and serves the
latest samples/history through an internally authenticated FastAPI API. No
machine-learning dependencies or request-level/user-level telemetry are
collected.

## Local setup

Apply the migration once to the shared PostgreSQL database:

```powershell
docker compose up -d postgres
Get-Content -Raw .\ai-controller\sql\001_create_telemetry_tables.sql |
  docker exec -i adaptive-rate-limiter-postgres-1 psql -v ON_ERROR_STOP=1 `
    -U rate_limiter_app -d rate_limiter
```

Set `AI_CONTROLLER_API_KEY` to a random secret of at least 32 characters.
For Compose, add it to the existing repository-root `.env` (do not replace
its PostgreSQL settings). For local processes, export the settings from
`.env.example` into the shell. In PowerShell, install dependencies and start
the API and worker in separate terminals:

```powershell
cd .\ai-controller
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Configure `DB_PASSWORD` and the other values from `.env.example`. Set
`AI_CONTROLLER_PROMETHEUS_URL=http://localhost:9090` when running outside
Docker.

```powershell
uvicorn app.main:app --host 127.0.0.1 --port 8000
python -m app.scheduler.collection_scheduler
```

The worker holds a PostgreSQL session-level advisory lock for its lifetime.
Additional worker replicas wait for the lock; a worker crash releases it
when its database connection closes. Unique window constraints and
conflict-safe writes prevent duplicate samples after restarts.

In Compose, `ai-controller-api` and `ai-controller-worker` are separate
services. Apply the migration before starting either. Provide
`AI_CONTROLLER_API_KEY` through the environment or an uncommitted root `.env`;
the API refuses telemetry access if it is missing. The API port is bound to
loopback, and telemetry endpoints also require `X-Internal-API-Key`.

Apply forecasting storage after the telemetry migration:

```powershell
Get-Content -Raw .\ai-controller\sql\002_create_traffic_forecasts.sql |
  docker exec -i adaptive-rate-limiter-postgres-1 psql -v ON_ERROR_STOP=1 `
    -U rate_limiter_app -d rate_limiter
```

After migration `002`, apply migration `003` to allow the same target to
retain forecasts generated at different horizons (including on fresh
installations):

```powershell
Get-Content -Raw .\ai-controller\sql\003_forecast_horizon_uniqueness.sql |
  docker exec -i adaptive-rate-limiter-postgres-1 psql -v ON_ERROR_STOP=1 `
    -U rate_limiter_app -d rate_limiter
```

Apply recommendation storage after migration `003`:

```powershell
Get-Content -Raw .\ai-controller\sql\004_create_policy_recommendations.sql |
  docker exec -i adaptive-rate-limiter-postgres-1 psql -v ON_ERROR_STOP=1 `
    -U rate_limiter_app -d rate_limiter
```

Set recommendation controls with `AI_CONTROLLER_MAX_CHANGE_PERCENT`,
`AI_CONTROLLER_RECOMMENDATION_COOLDOWN_SECONDS`,
`AI_CONTROLLER_MINIMUM_FORECAST_CONFIDENCE`, and
`AI_CONTROLLER_MAXIMUM_TELEMETRY_AGE_SECONDS`. The default overload thresholds
can also be set with `AI_CONTROLLER_MAXIMUM_CPU_UTILIZATION`,
`AI_CONTROLLER_MAXIMUM_P95_LATENCY_MS`, `AI_CONTROLLER_MAXIMUM_P99_LATENCY_MS`,
`AI_CONTROLLER_MAXIMUM_5XX_RATE`, and `AI_CONTROLLER_MAXIMUM_QUEUE_DEPTH`.
No safe capacity is inferred from forecasts: `safe_capacity_rps` must come
from load testing and SLO measurements.

Apply validation-history storage after migration `004`:

```powershell
Get-Content -Raw .\ai-controller\sql\005_create_recommendation_validations.sql |
  docker exec -i adaptive-rate-limiter-postgres-1 psql -v ON_ERROR_STOP=1 `
    -U rate_limiter_app -d rate_limiter
```

Apply shadow evaluation storage after migration `005`:

```powershell
Get-Content -Raw .\ai-controller\sql\006_create_shadow_evaluations.sql |
  docker exec -i adaptive-rate-limiter-postgres-1 psql -v ON_ERROR_STOP=1 `
    -U rate_limiter_app -d rate_limiter
```

Apply the Policy Service execution ledger and kill-switch migrations, then the
Policy Service service-version/rollback migration, and then the AI Controller
execution history and rollback-event migrations. These migrations use the same
PostgreSQL database as the services; the session timezone is set for each
application and does not change the database-wide timezone:

```powershell
$dbPasswordLine = Get-Content .\.env |
  Where-Object { $_ -match '^POSTGRES_PASSWORD=' } |
  Select-Object -First 1
$env:PGPASSWORD = $dbPasswordLine.Substring('POSTGRES_PASSWORD='.Length).Trim().Trim('"').Trim("'")
$env:TZ = 'Asia/Kolkata'

foreach ($migration in @(
  '.\policy-service\src\main\resources\db\006_service_execution_requests.sql',
  '.\policy-service\src\main\resources\db\007_policy_execution_control.sql',
  '.\policy-service\src\main\resources\db\008_service_config_history_and_rollback.sql',
  '.\ai-controller\sql\007_create_policy_executions.sql',
  '.\ai-controller\sql\008_create_policy_rollback_events.sql',
  '.\ai-controller\sql\009_create_circuit_breakers.sql'
)) {
  $sql = "BEGIN;`nSET LOCAL TIME ZONE 'Asia/Kolkata';`n" +
    (Get-Content -Raw $migration) + "`nCOMMIT;`n"
  $sql | docker exec -i -e "PGPASSWORD=$env:PGPASSWORD" `
    adaptive-rate-limiter-postgres-1 psql -v ON_ERROR_STOP=1 `
    -U rate_limiter_app -d rate_limiter
  if ($LASTEXITCODE -ne 0) { throw "Migration failed: $migration" }
}
Remove-Item Env:PGPASSWORD
```

The circuit breaker stores per-service `CLOSED`, `OPEN`, and `HALF_OPEN`
state, immutable transition events, independent component health, and durable
execution reservations. Apply migration `009` before starting the updated
controller. A PostgreSQL row lock protects the state check and reservation;
an interrupted reservation remains fail-closed for operator reconciliation.
The Gateway continues enforcing its existing policy and does not depend on
the controller.

The breaker defaults to opening after three consecutive execution failures,
waiting 300 seconds before recovery, and allowing one recovery recommendation
with at most a 2% change. All thresholds are configurable with the
`AI_CONTROLLER_BREAKER_*` variables in `.env.example`. The controlled reset
endpoint also verifies fresh telemetry, recent forecast accuracy, the Policy
Service configuration, and the effective Redis policy before entering
`HALF_OPEN`. Manual disable remains active until an administrator explicitly
sets `clear_manual_disable` on reset.

Circuit breaker endpoints (internal API key required; manual operations also
require `X-Admin-API-Key`):

- `GET /api/v1/circuit-breaker/{serviceKey}` — current service and component health
- `POST /api/v1/circuit-breaker/{serviceKey}/open` — manually disable adaptive control
- `POST /api/v1/circuit-breaker/{serviceKey}/reset` — request controlled recovery
- `GET /api/v1/circuit-breaker/{serviceKey}/history` — immutable state transitions

## Tenant allocation

Migration `010_create_tenant_allocations.sql` adds tenant allocation
configuration, immutable run metadata, and per-tenant results. Apply it after
migration `009`:

```powershell
$sql = "BEGIN;`nSET LOCAL TIME ZONE 'Asia/Kolkata';`n" +
  (Get-Content -Raw .\ai-controller\sql\010_create_tenant_allocations.sql) +
  "`nCOMMIT;`n"
$sql | docker exec -i adaptive-rate-limiter-postgres-1 psql `
  -v ON_ERROR_STOP=1 -U rate_limiter_app -d rate_limiter
```

Configure tenant priorities, weights, minimums, maximums, adaptive-control
switches, predicted demand, and current allocations through
`PUT /api/v1/allocations/{serviceKey}/tenants`. Higher `tenant_priority`
multiplies a tenant's configured weight; it is not a strict priority tier.
`POST /api/v1/allocations/evaluate/{serviceKey}` accepts an explicit
`global_capacity_rps`, which must be the load-tested safe service capacity,
not the token bucket's burst capacity or the Gateway's current refill rate.
Evaluation applies weighted water-filling, refuses impossible minimum
guarantees, and stores reproducible immutable runs. Allocation APIs require
`X-Internal-API-Key`.

Read the latest output and run history with
`GET /api/v1/allocations/{serviceKey}/latest` and
`GET /api/v1/allocations/{serviceKey}/history`. Metrics include utilization,
demand-fulfillment and weighted-entitlement Jain indices, estimated rejection,
starvation duration, and allocation oscillation.

Allocation runs are control-plane results only and do not update live policy.
The Gateway continues atomically enforcing tenant-wide, tenant-route, and
global token buckets. Live deployment is deliberately not wired to per-route
policy updates: the Policy Service/Gateway need a tenant-wide versioned
allocation config synchronized as one Redis value before applying a tenant
allocation across routes. Updating route snapshots independently could
temporarily give the shared tenant bucket inconsistent refill settings.

### Route allocation (shadow mode)

Apply `011_create_route_allocations.sql` after tenant allocation migration `010`:

```powershell
$sql = "BEGIN;`nSET LOCAL TIME ZONE 'Asia/Kolkata';`n" +
  (Get-Content -Raw .\ai-controller\sql\011_create_route_allocations.sql) +
  "`nCOMMIT;`n"
$sql | docker exec -i adaptive-rate-limiter-postgres-1 psql `
  -v ON_ERROR_STOP=1 -U rate_limiter_app -d rate_limiter
```

Route configuration is replaced with
`PUT /api/v1/allocation/routes/{serviceKey}/configs`. Each
`resource_cost_factor` must come from measured backend resource consumption;
it is never inferred from URL or HTTP method. Run
`POST /api/v1/allocation/routes/{serviceKey}/evaluate` with a
load-test-calibrated `backend_resource_budget` expressed in the same resource
units per second. The engine requires a prior tenant allocation run, uses its
global capacity and tenant allocations as hard ceilings, and rejects minimums
that exceed tenant, global, or backend resource budgets. Results are shadow
only and retain the exact tenant-run ID and route inputs used.

Inspect the latest run at `GET /api/v1/allocation/routes/{serviceKey}`, the
history at `/history`, and the latest two-run comparison at `/comparison`.
These APIs require `X-Internal-API-Key`. No live Policy Service or Redis
configuration is changed by a route allocation run.

The Compose stack also runs a dedicated `ai-controller-forecast-worker`.
Forecasting starts after it has 20 recent, contiguous samples with incoming
RPS values; missing, stale, invalid, or non-contiguous telemetry is never
imputed. It benchmarks moving average, simple exponential smoothing, and
Holt's linear trend at 30- and 60-second horizons. The worker uses a distinct
PostgreSQL advisory lock so only one replica creates forecasts.

## SLA-aware tenant allocation (shadow mode)

Apply `012_create_tenant_sla.sql` after route allocation migration `011`:

```powershell
$dbPasswordLine = Get-Content .\.env |
  Where-Object { $_ -match '^POSTGRES_PASSWORD=' } |
  Select-Object -First 1
$env:PGPASSWORD = $dbPasswordLine.Substring('POSTGRES_PASSWORD='.Length).Trim().Trim('"').Trim("'")
$env:TZ = 'Asia/Kolkata'
$sql = "BEGIN;`nSET LOCAL TIME ZONE 'Asia/Kolkata';`n" +
  (Get-Content -Raw .\ai-controller\sql\012_create_tenant_sla.sql) +
  "`nCOMMIT;`n"
$sql | docker exec -i -e "PGPASSWORD=$env:PGPASSWORD" `
  adaptive-rate-limiter-postgres-1 psql -v ON_ERROR_STOP=1 `
  -U rate_limiter_app -d rate_limiter
if ($LASTEXITCODE -ne 0) { throw 'SLA migration failed' }
Remove-Item Env:PGPASSWORD
```

`PUT /api/v1/sla/{serviceKey}/tenants` upserts versioned tenant SLA
configurations. Omitted values use the configurable tier defaults: Basic
priority/weight/minimum/maximum `1/1/50/150`, Pro `2/2/100/400`, and
Enterprise `3/4/200/800`. These are example defaults, not commercial
commitments. `POST /api/v1/sla/{serviceKey}/evaluate` requires the
load-tested global service capacity, rejects impossible guarantees, reserves
minimums, then distributes remaining capacity deterministically by
`allocation_weight * priority` while respecting demand and maximum rates.
Route minimums are checked against each tenant's proposed allocation.
Allocation runs retain immutable references to the exact SLA configuration
versions used. They are proposals only and do not update Policy Service,
Redis, or Gateway token buckets.

Read configuration with `GET /api/v1/sla/{serviceKey}/tenants` or
`GET /api/v1/sla/{serviceKey}/tenants/{tenantId}`, proposals with
`GET /api/v1/sla/{serviceKey}/allocation-history`, and the report with
`GET /api/v1/sla/{serviceKey}/compliance`. All SLA endpoints require
`X-Internal-API-Key`. Compliance remains `NOT_MEASURABLE` until telemetry is
tenant-scoped: a rate allocation proposal alone does not establish actual
admitted throughput, throttling, latency, errors, or availability. Projected
throttle relative to `max_throttle_ratio` is reported separately from
measured compliance.

## Benchmarking (isolated test environments only)

Apply `013_create_benchmarking.sql` after migrations `010`-`012`, then apply
`014_add_benchmark_dropped_iterations.sql` and
`015_add_policy_submission_timestamps.sql` (after `007_create_policy_executions.sql`),
then `016_create_chaos_experiments.sql`:

```powershell
$dbPasswordLine = Get-Content .\.env |
  Where-Object { $_ -match '^POSTGRES_PASSWORD=' } |
  Select-Object -First 1
$env:PGPASSWORD = $dbPasswordLine.Substring('POSTGRES_PASSWORD='.Length).Trim().Trim('"').Trim("'")
$env:TZ = 'Asia/Kolkata'
$sql = "BEGIN;`nSET LOCAL TIME ZONE 'Asia/Kolkata';`n" +
  (Get-Content -Raw .\ai-controller\sql\013_create_benchmarking.sql) +
  "`nCOMMIT;`n"
$sql | docker exec -i -e "PGPASSWORD=$env:PGPASSWORD" `
  adaptive-rate-limiter-postgres-1 psql -v ON_ERROR_STOP=1 `
  -U rate_limiter_app -d rate_limiter
if ($LASTEXITCODE -ne 0) { throw 'Benchmark migration failed' }
Remove-Item Env:PGPASSWORD
```

```powershell
$dbPasswordLine = Get-Content .\.env |
  Where-Object { $_ -match '^POSTGRES_PASSWORD=' } |
  Select-Object -First 1
$env:PGPASSWORD = $dbPasswordLine.Substring('POSTGRES_PASSWORD='.Length).Trim().Trim('"').Trim("'")
$env:TZ = 'Asia/Kolkata'
$sql = "BEGIN;`nSET LOCAL TIME ZONE 'Asia/Kolkata';`n" +
  (Get-Content -Raw .\ai-controller\sql\016_create_chaos_experiments.sql) +
  "`nCOMMIT;`n"
$sql | docker exec -i -e "PGPASSWORD=$env:PGPASSWORD" `
  adaptive-rate-limiter-postgres-1 psql -v ON_ERROR_STOP=1 `
  -U rate_limiter_app -d rate_limiter
if ($LASTEXITCODE -ne 0) { throw 'Chaos testing migration failed' }
Remove-Item Env:PGPASSWORD
```

```powershell
$dbPasswordLine = Get-Content .\.env |
  Where-Object { $_ -match '^POSTGRES_PASSWORD=' } |
  Select-Object -First 1
$env:PGPASSWORD = $dbPasswordLine.Substring('POSTGRES_PASSWORD='.Length).Trim().Trim('"').Trim("'")
$env:TZ = 'Asia/Kolkata'
$sql = "BEGIN;`nSET LOCAL TIME ZONE 'Asia/Kolkata';`n" +
  (Get-Content -Raw .\ai-controller\sql\015_add_policy_submission_timestamps.sql) +
  "`nCOMMIT;`n"
$sql | docker exec -i -e "PGPASSWORD=$env:PGPASSWORD" `
  adaptive-rate-limiter-postgres-1 psql -v ON_ERROR_STOP=1 `
  -U rate_limiter_app -d rate_limiter
if ($LASTEXITCODE -ne 0) { throw 'Policy execution timestamp migration failed' }
Remove-Item Env:PGPASSWORD
```

```powershell
$dbPasswordLine = Get-Content .\.env |
  Where-Object { $_ -match '^POSTGRES_PASSWORD=' } |
  Select-Object -First 1
$env:PGPASSWORD = $dbPasswordLine.Substring('POSTGRES_PASSWORD='.Length).Trim().Trim('"').Trim("'")
$env:TZ = 'Asia/Kolkata'
$sql = "BEGIN;`nSET LOCAL TIME ZONE 'Asia/Kolkata';`n" +
  (Get-Content -Raw .\ai-controller\sql\014_add_benchmark_dropped_iterations.sql) +
  "`nCOMMIT;`n"
$sql | docker exec -i -e "PGPASSWORD=$env:PGPASSWORD" `
  adaptive-rate-limiter-postgres-1 psql -v ON_ERROR_STOP=1 `
  -U rate_limiter_app -d rate_limiter
if ($LASTEXITCODE -ne 0) { throw 'Benchmark follow-up migration failed' }
Remove-Item Env:PGPASSWORD
```

The API only queues bounded work; a separate, opt-in `benchmark` profile worker
executes k6 and collects metrics. Build and start it with
`docker compose --profile benchmark up -d --build
ai-controller-benchmark-worker`, after configuring
`AI_CONTROLLER_BENCHMARK_TARGET_URL`, the allowed local test hosts, and the
test route paths. Set `AI_CONTROLLER_GIT_COMMIT` to the exact source revision.
Do not point it at production or a third-party host. The worker only permits
explicitly allowlisted host-and-port pairs such as
`host.docker.internal:8080`. Configure
`AI_CONTROLLER_BENCHMARK_TENANT_TOKENS` with one comma-separated, isolated
test JWT per tenant; those tokens are passed to k6 from the worker environment
and are never persisted. Their JWT `tenant_id` claims must correspond to
`benchmark-tenant-0` through `benchmark-tenant-N`. k6 starts at a modest rate
(10 RPS by default), caps requested rates at 1,000 RPS, and duration at 3,600
seconds. The worker's conservative `AI_CONTROLLER_BENCHMARK_MAX_RPS` default
is 100; raise it only after confirming local capacity and increasing load
gradually.

Each request must explicitly confirm an isolated test environment, supply
an `environment_id` shared by all three runs, version identifiers for all
three configurations, and supply the backend's
approved SLO thresholds (p95/p99 latency, backend-error ratio, SLA violations,
fairness, CPU/memory, Redis latency/errors, rejection ratio, and minimum
successful RPS). These values are required instead of being guessed. The
environment ID, Git commit, workload parameters, route paths, SLOs, strategy
versions, and k6 script version are retained for reproducibility. A test
target/adapter must apply the selected strategy and
return `X-Benchmark-Active-Strategy` and
`X-Benchmark-Active-Config-Version` matching the requested strategy and version
on every response. Runs fail closed if the target cannot confirm which
configuration handled the request. This worker does not change Policy Service,
Redis, Gateway policies, or inject faults. The SLA allocator remains shadow
only; therefore, a measured AI-SLA strategy requires a separately approved
isolated test adapter that applies its proposal and confirms its active
version. Backend degradation, Redis failure, controller failure, and policy
sync delay scenarios require operators to arrange faults in that isolated
environment and explicitly confirm them; the benchmark does not induce
failures.

`POST /api/v1/benchmarks/run` enqueues one run per strategy with the same
scenario, workload parameters, and SLOs; execution order rotates across
batches to reduce ordering bias. Available scenarios: steady traffic, sudden
spike, gradual ramp, burst traffic, tenant hotspot, route imbalance, backend
degradation, Redis failure, controller failure, and policy sync delay.
The k6 script measures incoming/accepted/successful RPS, 429 rejection ratio,
5xx ratio among admitted requests, generator-dropped iterations, and latency
percentiles separately. Prometheus and durable
controller records provide resource, Redis, forecast, policy, and SLA metrics;
unavailable measurements remain null and fail any corresponding SLO check.
Jain fairness is calculated from per-tenant demand fulfillment, not raw
throughput. Results include metric variability across repeated runs. Reports
compare against STATIC and list regressions; they do not assume an adaptive
strategy is better. Policy application time measures the Policy Service submit
round-trip; propagation delay measures from confirmed submission until the
effective policy is verified. Ambiguous submissions without exact confirmation
remain unmeasured rather than being estimated.
Redis hot-key behaviour is explicitly unavailable unless a separate,
approved key-level instrumentation source is configured; the benchmark does
not add high-cardinality per-key labels to production metrics.
Prometheus collection errors and unavailable metrics are listed in the
comparison report and stored on each result.

Use the returned run IDs with `GET /api/v1/benchmarks/{runId}` and
`GET /api/v1/benchmarks/{runId}/results`; compare a batch with
`GET /api/v1/benchmarks/compare?service_key=orders-service&scenario=STEADY_TRAFFIC&batch_id={batchId}`,
or compare recent repeated batches with `repeats`. `GET
/api/v1/benchmarks/history?service_key=orders-service` lists run history.
These routes require `X-Internal-API-Key`.

## Chaos testing (manual, authorized local Compose environment only)

Chaos injection is disabled by default. Only CH-01 (Redis unavailable) is
implemented; CH-02 through CH-10 are rejected with HTTP 501 and are not queued.
The API only queues experiments. Run the separate worker manually on the host;
it has no Docker socket in the API container and accepts no shell commands or
service names from API requests.

Before enabling it, use an isolated local Compose project with the approved
`redis:7.4` service and configure a protected route that should fail closed
with HTTP 503 when Redis is unavailable. Set
`AI_CONTROLLER_CHAOS_ENABLED=true` and a unique
`AI_CONTROLLER_CHAOS_TEST_ENVIRONMENT_ID` in the API environment. The API
requires both `X-Internal-API-Key` and `X-Admin-API-Key` to queue a run; the
administrator key must be at least 32 characters. On the host, configure the
worker with that same test environment ID, a local
`AI_CONTROLLER_CHAOS_COMPOSE_PROJECT_DIRECTORY`, an in-project
`AI_CONTROLLER_CHAOS_COMPOSE_FILE`, the exact protected-route
`AI_CONTROLLER_CHAOS_PROBE_URL`, and a matching host-and-port in
`AI_CONTROLLER_CHAOS_ALLOWED_HOSTS`. Set ordinary database environment
variables so the local worker can connect to PostgreSQL. Optionally set
`AI_CONTROLLER_CHAOS_PROBE_AUTHORIZATION` to a test-only bearer authorization
value; it is never persisted. Keep the environment ID and URL out of production
configuration.

After applying migration 016, start the API normally. In a separate host
PowerShell session with the controller dependencies and database environment
available, start the one-at-a-time worker:

```powershell
$env:AI_CONTROLLER_CHAOS_ENABLED = 'true'
$env:AI_CONTROLLER_CHAOS_TEST_ENVIRONMENT_ID = 'local-chaos-test'
$env:AI_CONTROLLER_CHAOS_COMPOSE_PROJECT_DIRECTORY = 'C:\path\to\isolated-test-compose'
$env:AI_CONTROLLER_CHAOS_COMPOSE_FILE = 'compose.yaml'
$env:AI_CONTROLLER_CHAOS_PROBE_URL = 'http://localhost:8080/protected-route'
$env:AI_CONTROLLER_CHAOS_ALLOWED_HOSTS = 'localhost:8080'
python -m app.chaos.chaos_worker
```

Submit only after verifying that all traffic in the configured route is test
traffic. The request must match the configured environment ID, service key,
and include both confirmation flags. Fault duration is bounded to 30 seconds
and capped by `AI_CONTROLLER_CHAOS_FAULT_DURATION_SECONDS`. Before stopping
Redis, the worker verifies the local Docker context, the Compose Redis image,
and a healthy protected-route preflight. It always attempts to start Redis in
the fault cleanup path; then it checks Redis `PING` and the protected route for
up to 30 seconds. If the stop command fails ambiguously, the worker still
attempts to start the fixed Redis service and verifies recovery. The worker
rejects `DOCKER_HOST` overrides and requires a local named-pipe or Unix-socket
daemon endpoint; a Docker context name alone is not treated as proof of locality.
A failed recovery is recorded as unsuccessful. If the worker lease expires,
the experiment is marked failed and the operator must verify Redis and route
recovery manually before queuing another experiment.

CH-01 records request status/latency samples, the confirmed Redis restart and
route recovery, and whether the protected route returned 503 during the fault.
Policy version and disabled-policy state are marked as not independently
measured by CH-01; policy consistency is not inferred from Redis health. Token
deduction atomicity, cross-replica Redis state, and bucket reconstruction also
remain unverified without dedicated instrumentation. Do not treat this
single-scenario implementation as evidence that the ten-scenario chaos
milestone is complete. No automated test stops or restarts real containers.

## Metrics

Configured `AI_CONTROLLER_SERVICE_KEYS` (comma-separated) are queried using
their bounded Gateway `service` label and application `application` label.
The collector uses:

- `ratelimit_requests_total{service=...}` for incoming/allowed/rejected RPS.
- `http_server_requests_seconds_bucket` for p95/p99 latency.
- `http_server_requests_seconds_count{status=~"5.."}` for 5xx requests/sec.
- `process_cpu_usage` and JVM heap used/max for utilization.
- `ratelimit_redis_latency_seconds_bucket` for Redis p95 latency.
- `policy_outbox_pending` for policy queue depth.

Missing values remain `NULL`; invalid, missing, partial, and stale samples
are explicitly marked. The configured staleness limit defaults to 60
seconds. Collection defaults to every 15 seconds. Aggregates use the most
recent five minutes and are stored separately in `telemetry_windows`;
`missing_sample_count` includes absent and unusable expected sample slots.
The queue depth and Redis latency are shared infrastructure measurements
copied into each configured service's row.

## API

- `GET /health` is a liveness endpoint.
- `GET /api/v1/telemetry/latest/{serviceKey}`
- `GET /api/v1/telemetry/history/{serviceKey}?limit=100`
- `GET /api/v1/telemetry/status`
- `POST /api/v1/forecast/{serviceKey}` (optional JSON `{"horizons_seconds":[30,60]}`)
- `GET /api/v1/forecast/latest/{serviceKey}`
- `GET /api/v1/forecast/history/{serviceKey}?limit=100`
- `GET /api/v1/forecast/accuracy/{serviceKey}`
- `POST /api/v1/recommendations/evaluate/{serviceKey}`
- `GET /api/v1/recommendations/{serviceKey}/latest`
- `GET /api/v1/recommendations/{serviceKey}/history`
- `PATCH /api/v1/recommendations/{id}/accept` with
  `{"current_policy_version": <version>}`
- `PATCH /api/v1/recommendations/{id}/reject`
- `POST /api/v1/safety/validate/{recommendationId}`
- `GET /api/v1/safety/{recommendationId}/latest`
- `GET /api/v1/safety/{recommendationId}/history`
- `POST /api/v1/shadow/evaluate/{serviceKey}`
- `GET /api/v1/shadow/{serviceKey}/latest`
- `GET /api/v1/shadow/{serviceKey}/history`
- `GET /api/v1/shadow/{serviceKey}/comparison`
- `POST /api/v1/rollback/evaluate/{serviceKey}`
- `POST /api/v1/rollback/execute/{executionId}`
- `GET /api/v1/rollback/{serviceKey}/history`
- `GET /api/v1/rollback/{rollbackId}`

Send `X-Internal-API-Key: $AI_CONTROLLER_API_KEY` to telemetry and forecast routes.
Recommendation routes require the same internal API key. Evaluation input
includes the current global rate, service min/max and hard maximum, policy
version, safe capacity, forecast and confidence, and current health telemetry.
Recommendations have global scope; accepting one records approval only and
does not update the live policy. Safety validation accepts a current policy and
service snapshot (rate bounds, policy version, telemetry timestamp, safe
capacity, and adaptive-control eligibility), checks every rule, and persists
each attempt with a distinct ID. Cooldown checks consider other pending or
accepted rate-changing recommendations; a failed validation never mutates its
recommendation.
Shadow evaluation requires a passing, current validation and recent contiguous
telemetry. The request supplies the safety capacity, evaluation window,
representative tenant/route IDs, and rule-based rate. Current policy version,
global rate/capacity/hard maximum, adaptive eligibility, and active tenant and
route bucket capacities/refill rates are read from the shared policy database.
The evaluation compares the current static rate, supplied rule-based rate,
and validated forecast-assisted rate on the identical telemetry replay.
Apply migration `006` before using shadow routes.

The replay uses the Gateway's all-three-buckets admission rule, starting each
bucket full and refilling with elapsed time. Telemetry only contains
service-level aggregate RPS, so arrivals are distributed uniformly within
each recorded telemetry window and the service total is replayed through one
representative tenant/route pair. Sub-window bursts and per-tenant/route
distribution cannot be reconstructed from current telemetry; use finer
telemetry or request-level workload replay for that fidelity. Results report
admission estimates, not application success. Latency, 5xx, and CPU values
remain observed workload metrics and are not predictions for alternative
policies. Shadow evaluation never contacts the Gateway or Redis and never
changes the live policy.
Execution is disabled by default and requires a Policy Service API key, an
administrator API key, an explicit service allowlist, and the deployment
emergency switch to be cleared. The AI Controller submits version-checked,
idempotent changes only through the Policy Service. It leaves an execution
`SUBMITTED` until Redis reports the expected version and rate and the Gateway
policy-cache TTL has elapsed. Enable/disable controls fail closed: local
execution remains disabled until effective policy synchronization is verified.

Automatic rollback checks are run by the telemetry worker after each
collection cycle. Set `AI_CONTROLLER_POLICY_SERVICE_URL` and
`AI_CONTROLLER_POLICY_SERVICE_API_KEY` for the worker and set the matching
`POLICY_EXECUTION_API_KEY` in the Policy Service process; both values must be
the same random secret of at least 32 characters. In Compose, add
`POLICY_EXECUTION_API_KEY` to the root `.env`; the worker receives it under
the AI Controller setting name. Without the key, the worker fails closed and
logs that scheduled rollback is disabled. `POST
/api/v1/rollback/evaluate/{serviceKey}` only evaluates conditions;
`POST /api/v1/rollback/execute/{executionId}` initiates/resumes a triggered
rollback. The Policy Service records immutable service configuration
snapshots; a rollback requires the failed version to still be current and
creates a newer version restoring the earlier global capacity/rate. It then
disables adaptive control, records an outbox event, and the AI Controller
waits for the exact Redis version/rate and Gateway cache TTL before marking
the event complete. A concurrent administrator update is never overwritten.

Rollback thresholds are configurable with `AI_CONTROLLER_ROLLBACK_*`
settings. Defaults are p95 over 500 ms for 3 windows, 5xx over 5% for 2
windows, CPU over 90% for 3 windows, growing queue depth over 100 for 3
windows, throughput degradation over 30% for 3 windows, and a 60-second
minimum observation period. A 20% 5xx rate and Redis synchronization timeout
are immediate triggers. The 5xx percentage is derived from the observed
5xx-per-second metric divided by incoming RPS. After rollback, adaptive
control remains paused for a one-hour cooldown and until five fresh healthy
windows have been observed. Admin re-enablement is protected by the existing
administrator API key; use `{"manual_approval": true}` only after operator
review when a rollback failed or exceeded the hourly attempt limit.
Rollback failures increment
`ai_controller_rollback_failures_total` and raise the
`AdaptivePolicyRollbackFailed` Prometheus alert.
History is capped at 1,000 records per request. Worker collection errors are
recorded by type, without returning Prometheus/DB URLs or credentials.
The status endpoint reports configured services as `idle` before the first
collection and marks a formerly successful worker `stale` if updates stop.

Forecast accuracy uses chronological rolling-origin evaluation and reports
MAE, RMSE, WAPE, peak prediction error, and errors for high-traffic and
low-traffic observations. Prometheus exports forecast duration/failures,
freshness, model version, predicted RPS, accuracy, and forecast-to-actual
deviation. The Grafana dashboard overlays observed and predicted incoming
traffic. The forecast worker serves its Prometheus metrics on internal port
`8001`, which Prometheus scrapes; the API also serves `/metrics` for local
diagnostics.

Run tests with:

```powershell
pytest
```
