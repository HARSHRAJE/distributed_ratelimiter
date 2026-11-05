# Local monitoring stack

The local monitoring stack consists of Redis Exporter, Prometheus, and
Grafana. It is intended for local development and binds the monitoring UIs
and Redis Exporter to loopback:

| Component | URL |
|---|---|
| Prometheus | http://localhost:9090 |
| Grafana | http://localhost:3000 |
| Redis Exporter | http://localhost:9121/metrics |

The Spring services expose a separate management server:

| Service | Management URL |
|---|---|
| Gateway | http://localhost:9180/actuator/prometheus |
| Policy Service | http://localhost:9181/actuator/prometheus |
| Orders Service | http://localhost:9182/actuator/prometheus |

Start the application services as usual, then start the monitoring
containers from the repository root:

```powershell
$env:GRAFANA_ADMIN_PASSWORD = '<choose a local Grafana password>'
docker compose up -d redis-exporter prometheus grafana
```

The Grafana username defaults to `admin`; `GRAFANA_ADMIN_USER` and
`GRAFANA_ADMIN_PASSWORD` can be set in the environment or local `.env`.
The default password is for loopback-only local development. Set a unique
password before starting Grafana. Do not commit credentials.

Prometheus scrapes application management ports using
`host.docker.internal`, which Docker Desktop resolves to the host. Its target
list and alert rules are in `prometheus/prometheus.yml` and
`prometheus/alerts.yml`. Grafana provisions the Prometheus data source and the
Distributed Rate Limiter dashboard automatically.

## Metrics

The Gateway publishes:

- `ratelimit_requests_total`, with finite `service` and `outcome` labels;
  rejections also have `limit_type` (`tenant`, `route`, `service`, or
  `policy`).
- `ratelimit_policy_cache_total`, tagged only by `outcome` (`hit`/`miss`).
- `ratelimit_policy_lookup_seconds` and
  `ratelimit_redis_latency_seconds` histograms.
- Spring HTTP server request and JVM metrics.

The Policy Service publishes:

- `policy_outbox_pending`, `policy_outbox_processing`, and
  `policy_outbox_failed` gauges.
- `policy_outbox_sync_lag`, the age in seconds of the oldest pending event.
- `policy_outbox_exhausted_total`, a counter of events that exhausted retries.
- Spring HTTP server request and JVM metrics.

Orders Service publishes Spring HTTP server request and JVM metrics. Redis
Exporter reports Redis memory, connected clients, command activity, keyspace,
CPU, evictions, and availability.

No tenant ID, user ID, request ID, or arbitrary request path is used as a
Prometheus label. The `service` label is the configured Gateway service key;
keep its set finite.

## Access control

Monitoring UI and exporter host ports are bound to `127.0.0.1`. Prometheus
scrapes the service management ports 9180-9182; the Gateway Prometheus scrape
path is unauthenticated so Prometheus can collect it. These management ports
must remain reachable only from the host and trusted monitoring network.
Configure the host firewall to block ports 9180-9182 from untrusted
interfaces before using this beyond a local workstation. Do not publish
management ports through a public load balancer or ingress.

## Alerts and tuning

Starter alerts cover scrape-target outages, Redis availability, exhausted
outbox events, pending backlog growth, and synchronization lag. Tune warning
thresholds with observed test and production baselines; the five-minute
sync-lag threshold is an initial operational signal, not an SLO. High
rejection-rate and latency alerts are intentionally not assigned arbitrary
thresholds.

Open Prometheus **Status → Targets** and verify `gateway`, `policy-service`,
`orders-service`, and `redis` are `UP`. Open Grafana and select the
**Distributed Rate Limiter** dashboard.
