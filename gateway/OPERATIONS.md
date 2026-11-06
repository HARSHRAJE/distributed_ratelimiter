# Gateway capacity and readiness

The Gateway enforces tenant, route, and global buckets with a single reactive
Redis Lua call. Rejected calls do not consume tokens from any bucket. Redis
policy snapshots are resolved reactively and cached locally; PostgreSQL and
the Policy Service are not called from the request path. Proxy request bodies
are not cached or aggregated by the rate-limit filter.

## Initial connection and lifecycle settings

The initial settings in `src/main/resources/application.yml` are tuning
starting points, not production guarantees:

- Redis connect timeout: 2 seconds; command timeout: 100 ms.
- Lettuce pool: 100 active, 30 idle, 10 minimum idle, bounded 100 ms wait.
- Downstream pool: 500 connections with a bounded 1 second acquire timeout.
- Graceful shutdown: 30 seconds; liveness and readiness are separate.
- Policy cache: 1 second TTL and 100,000-entry maximum.

Benchmark these values against the target deployment. Override them through
the corresponding `REDIS_*`, `GATEWAY_*`, and `RATE_LIMIT_POLICY_CACHE_*`
environment variables. Rate-limit token deductions intentionally have no
automatic retry: after a network timeout, the caller cannot know whether Redis
executed the atomic script, so retrying could deduct twice.

## Redis state and capacity

The Compose Redis service uses AOF persistence, a persistent volume, a bounded
memory budget, and `noeviction`. When memory is exhausted, Redis writes fail
and the Gateway returns controlled errors; it must not silently evict active
token buckets. Choose `REDIS_MAX_MEMORY` below the Compose Redis memory limit
with room for AOF buffers and allocator overhead. Do not change the memory
policy without revalidating enforcement guarantees.

Bucket hashes expire only after enough idle time has elapsed for that bucket
to refill to capacity. The Lua update and expiry operation are atomic. Monitor
`redis_memory_used_bytes`, `redis_memory_max_bytes`,
`redis_connected_clients`, `redis_commands_processed_total`,
`redis_cpu_sys_seconds_total`, `redis_cpu_user_seconds_total`, and
`redis_evicted_keys_total`, along with
`ratelimit_redis_latency_seconds` and
`gateway_ratelimit_redis_script_seconds`. Redis database key counts provide an
approximation of active buckets because policy and service keys share the
database. Use bounded `SCAN` sampling and Redis `--hotkeys` diagnostics during
controlled maintenance; do not run blocking key scans on a busy primary.
Cluster hash-slot testing is not part of local Compose validation.
All tenant, route, and service bucket keys for one service intentionally share
its Redis hash tag so the Lua script can enforce them atomically. Consequently,
a Redis Cluster does not spread one service's enforcement load across hash
slots; measure the hot-slot ceiling before adopting Cluster as a throughput
scaling strategy.

The Gateway metrics include policy cache size, maximum size, oldest cached
entry age, expired lookups, evictions, and rejected stale updates. Its TTL
forces periodic refresh from Redis. Cache replacement is atomic and refuses
snapshots whose sync revision, active policy version, or service config
version is lower than the cached version. The Redis synchronization layer must
remain the source of truth; cache metrics and the stale-update alert are not a
substitute for measuring propagation lag.

## Capacity benchmark profiles

The benchmark API accepts optional `capacity_profile` values. Each strategy
in the batch receives the same profile and persisted workload parameters:

| Profile | Duration | Workload |
|---|---:|---|
| `BASELINE` | 300 s | Steady traffic at `start_rps` |
| `LOAD` | 600 s | Sustained expected peak at `peak_rps` |
| `STRESS` | 60 s or longer | Four-step ramp to peak; k6 stops on configured p95/p99, 5xx, or 429 SLO breach and retains the partial measurement |
| `SPIKE` | 300 s | Baseline, abrupt peak, then recovery |
| `SOAK` | 3,600–14,400 s | Sustained peak traffic |
| `RECOVERY` | 600 s | Peak phase followed by baseline recovery |

Set `AI_CONTROLLER_BENCHMARK_MAX_DURATION_SECONDS` to at least 14,400 in both
the API and worker environments to allow a four-hour soak. The default cap is
one hour. Keep the existing isolated-environment, route allowlist, tenant JWT,
and SLO confirmations in place. A stress test is bounded by the configured
maximum duration and RPS; it is not an unlimited test.

## Container resource limits

Compose applies CPU and memory limits to every service declared in the root
`compose.yaml`, including Redis, PostgreSQL, monitoring, and AI Controller
workers. The Gateway, Policy Service, and application backends are not
declared in that Compose project, so their limits must be set in their own
deployment configuration. For the Gateway, the example starting allocation
is 2 CPUs and 1 GB of memory; measure actual utilization before changing it.
Compose resource values are overridable through the service-specific
`*_CPU_LIMIT` and `*_MEMORY_LIMIT` variables.

## Readiness checklist

- [x] Reactive Redis operations and atomic token-bucket Lua enforcement.
- [x] Bounded Redis and downstream connection acquisition and explicit timeouts.
- [x] No blind retries of token-bucket deductions.
- [x] Redis-only policy lookup and bounded, version-aware local cache.
- [x] Streaming request-body behavior in the Gateway rate-limit filter.
- [x] Liveness/readiness separation and graceful shutdown configuration.
- [x] Redis bucket expiry, persistence, no-eviction memory policy, and alerts.
- [ ] Measure pool exhaustion and Redis memory exhaustion in an isolated test.
- [ ] Verify token conservation under concurrency against the production Redis topology.
- [ ] Verify horizontal Gateway scaling and Redis cluster slot distribution.
- [ ] Measure synchronization lag, recovery, and alert thresholds against benchmark results.
- [ ] Measure service utilization before changing resource allocations.

Control-plane circuit breakers belong on actual Gateway control-plane calls.
The request path currently makes no PostgreSQL or Policy Service calls, and
the AI Controller circuit breaker only prevents adaptive policy changes; it
does not disable normal Gateway enforcement. There are no Gateway
administrative endpoints or custom background executors to rate-limit or
bound in this application.
