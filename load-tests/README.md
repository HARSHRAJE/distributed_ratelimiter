# Distributed Gateway load tests

These k6 scenarios target the local `GET /api/orders` endpoint. They accept
`200` (allowed) and `429` (rate limited); authentication, policy, Redis, and
other server errors are counted as unexpected and fail the run. Provide real
short-lived access tokens through environment variables; never commit tokens
or place them in the scripts.

## Prerequisites and local topology

Install k6 from PowerShell and open a new terminal:

```powershell
winget install k6 --source winget
k6 version
```

Start Redis and PostgreSQL from the repository root:

```powershell
docker compose up -d redis postgres
```

Apply the database schemas/migrations and provision two test tenants, users,
active policies, and valid access tokens using the Auth Service and Policy
Service setup instructions. Ensure each policy's `tenantId` matches the
`tenant_id` claim in its access token. The Gateway resolves policies from
Redis, so wait for the corresponding outbox events to reconcile before
testing.

Run Orders Service on port `8082`, Auth Service on `8083`, and Policy Service
on `8084` in separate terminals. Policy Service defaults to `8081`, which
conflicts with the requested second Gateway port; override it for this test:

```powershell
$env:SERVER_PORT = '8084'
.\gateway\gradlew.bat -p .\policy-service bootRun
```

Run each Gateway in its own terminal, with the same Redis and Orders Service
settings and the same Auth Service public key. Use the actual public-key path
generated for your local Auth Service:

```powershell
$env:AUTH_PUBLIC_KEY_LOCATION = "file:$((Join-Path $HOME '.adaptive-rate-limiter\keys\auth-public.pem') -replace '\\','/')"
$env:REDIS_HOST = 'localhost'
$env:REDIS_PORT = '6379'
$env:ORDERS_SERVICE_URI = 'http://localhost:8082'
.\gateway\gradlew.bat -p .\gateway bootRun
```

For Gateway 2, use the same environment variables and additionally set
`$env:SERVER_PORT = '8081'` before running the command. Gateway 1 uses the
default port `8080`. Both instances must point to the same Redis server;
the token bucket keys are shared there.

For an optional Gateway-without-rate-limiting baseline, start a separate
Gateway with the test-only configuration below. It retains the normal JWT
security chain and binds to loopback on port `8085`; do not expose this
test-only instance to other hosts:

```powershell
$env:AUTH_PUBLIC_KEY_LOCATION = "file:$((Join-Path $HOME '.adaptive-rate-limiter\keys\auth-public.pem') -replace '\\','/')"
$env:ORDERS_SERVICE_URI = 'http://localhost:8082'
$baselineConfig = (Resolve-Path .\load-tests\gateway-baseline.yml).Path.Replace('\', '/')
.\gateway\gradlew.bat -p .\gateway bootRun --args="--spring.config.additional-location=file:$baselineConfig"
```

In the terminal running k6, set a valid token without putting it in source
control:

```powershell
$env:ACCESS_TOKEN = '<short-lived access token>'
```

## Scenarios

Basic rate limiting, 50 VUs for 30 seconds by default:

```powershell
k6 run -e "ACCESS_TOKEN=$env:ACCESS_TOKEN" .\load-tests\basic-rate-limit.js
```

A single concurrent wave (100 VUs, one request per VU). Set
`EXPECTED_MAX_ALLOWED` to assert an upper bound. For a deterministic
last-token test, use an isolated test Redis and policies with capacity `1`
and refill rate `0.001` for all three buckets, ensure no other traffic is
running, and set the bound to `1`. A missing bucket starts full; if buckets
already exist, their remaining state affects the result. Do not use
`FLUSHALL` against a shared Redis instance.

```powershell
k6 run -e "ACCESS_TOKEN=$env:ACCESS_TOKEN" -e EXPECTED_MAX_ALLOWED=1 .\load-tests\concurrent-requests.js
```

Two Gateway instances, with 25 VUs per instance by default:

```powershell
k6 run `
  -e "ACCESS_TOKEN=$env:ACCESS_TOKEN" `
  -e GATEWAY_1_URL=http://localhost:8080 `
  -e GATEWAY_2_URL=http://localhost:8081 `
  .\load-tests\distributed-gateway.js
```

Tenant isolation uses two separately provisioned active tenant policies and
tokens. The tenant labels in the k6 summary separate results; the global
service bucket is intentionally shared, so global exhaustion can limit both
tenants.

```powershell
$env:TENANT_A_TOKEN = '<tenant A access token>'
$env:TENANT_B_TOKEN = '<tenant B access token>'
k6 run `
  -e "TENANT_A_TOKEN=$env:TENANT_A_TOKEN" `
  -e "TENANT_B_TOKEN=$env:TENANT_B_TOKEN" `
  .\load-tests\tenant-isolation.js
```

The stress scenario ramps through 100, 500, and 1,000 VUs. Run it only
against an isolated test environment and monitor host resources:

```powershell
k6 run -e "ACCESS_TOKEN=$env:ACCESS_TOKEN" .\load-tests\stress-test.js
```

Set `BASE_URL`, `VUS`, `DURATION`, `SLEEP_SECONDS`, `VUS_PER_GATEWAY`,
`VUS_PER_TENANT`, `REQUEST_TIMEOUT`, or `MAX_DURATION` to adjust the
corresponding scenarios. The stress scenario supports `STRESS_LOW_VUS`,
`STRESS_MEDIUM_VUS`, `STRESS_HIGH_VUS`, `STRESS_RAMP_DURATION`,
`STRESS_HOLD_DURATION`, and `STRESS_COOLDOWN_DURATION` for shorter
smoke runs; defaults remain 100/500/1,000 VUs. Summaries include request throughput, p50, p95,
p99, and allowed, rate-limited, and unexpected response counts. The
`checks` and `load_test_unexpected_responses` thresholds require all responses
to be either `200` or `429`.

## Correctness, failures, and measurements

- The atomic Lua script checks and deducts all three buckets in one Redis
  operation. Use `concurrent-requests.js` with the isolated one-token setup
  above to exercise simultaneous contenders; use
  `distributed-gateway.js` to confirm both Gateways share those counters.
- For tenant isolation, configure tenant A's tenant limit low, tenant B's
  tenant limit higher, and the shared global limit high enough not to
  dominate the test. Compare the `tenant=A` and `tenant=B` k6 metrics.
- Compare the normal Gateway and the test-only baseline by running the same
  scenario sequentially with `BASE_URL` set to `http://localhost:8080` and
  `http://localhost:8085`, respectively. Keep JWT security enabled and use
  the same backend, token, and host conditions for both runs.
- Redis script latency is exposed as
  `http://localhost:9180/actuator/metrics/gateway.ratelimit.redis.script`.
  The Prometheus histograms for Redis and policy resolution are exported from
  the Gateway management port. Collect
  it before and after each run with an authenticated request. k6 reports
  request throughput and latency; use `docker stats` and Windows process
  monitoring for CPU and memory.
- Policy Service is not called on the request path. Stopping it after
  snapshots have reconciled should not affect requests while Redis remains
  healthy. The one-second policy cache is per Gateway and Redis remains the
  configuration source of truth.
- In an isolated environment, stop Redis and verify a protected request
  returns controlled `503`, then restart it and verify recovery. Missing or
  malformed policy snapshots should also fail closed. Do not perform
  destructive Redis tests against a shared or production instance.
- `compose.yaml` enables Redis AOF on a persistent Docker volume, but uses
  Redis's default AOF fsync policy and has no replica/failover. This is
  suitable for local restart checks, not a strict guarantee against losing
  the most recent bucket updates after a host or storage failure. Stronger
  quota durability requires an explicitly selected persistence and
  replication policy, with its latency and recovery tradeoffs measured.

Run scenarios sequentially when comparing results, use the same policy
configuration and test tokens, and save each k6 summary with the run's
environment and Redis/Gateway topology. Do not infer production targets from
these local measurements.
