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

Send `X-Internal-API-Key: $AI_CONTROLLER_API_KEY` to telemetry routes.
History is capped at 1,000 records per request. Worker collection errors are
recorded by type, without returning Prometheus/DB URLs or credentials.
The status endpoint reports configured services as `idle` before the first
collection and marks a formerly successful worker `stale` if updates stop.

Run tests with:

```powershell
pytest
```
