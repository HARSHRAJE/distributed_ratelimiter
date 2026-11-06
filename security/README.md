# Security boundary test module

This directory separates security-oriented checks and operator procedures
from the Gateway's runtime enforcement code. Run checks only against
disposable local test data. No test in this module is authorized to stop a
service, exhaust resources, brute-force credentials, or target a public host.

## Boundaries and current coverage

| Area | Automated coverage / control | Remaining verification |
|---|---|---|
| Authentication | Auth Service and Gateway enforce RS256, issuer, audience, token type, timestamp and tenant/user claims; refresh tokens are random, hashed, rotated and reuse-revoked | Add Auth Service HTTP-level tests for each invalid-token case and concurrency-safe refresh reuse |
| Authorization | Policy Service now requires JWT roles for human APIs; tenant reads are tenant-scoped; service admins require explicit `service_keys` claims; AI execution paths retain a separate execution key | Provision roles/memberships through an audited admin workflow and test HTTP response codes for each role |
| Tenant isolation | Gateway replaces duplicate/spoofed `X-Tenant-Id` and `X-User-Id` headers from validated JWT claims; Policy Service authorization helpers are unit tested | Exercise two tenants against a dedicated seeded test database and route set |
| Gateway bypass | Backend and Policy Service are not published by the root Compose file; Redis/PostgreSQL and monitoring ports bind to loopback | Verify deployed firewall/network policy and test direct service addresses only in an isolated environment |
| Redis | [generate_acl.py](./redis/generate_acl.py) creates separate restricted ACL users; Redis Compose requires an ACL file and monitoring credentials; gateway and Policy Service use distinct usernames | Provision secrets, verify ACL command/key restrictions and TLS in the target deployment; local loopback is not a production network boundary |
| Policy security | Policy endpoints use RS256 resource-server authentication, role checks, service/tenant scope checks, hard-bound validation, expected-version checks and execution idempotency | Add HTTP integration tests for unauthorized calls, stale versions, duplicate requests and adaptive-control kill switch |
| AI Controller | Strict Pydantic schemas, independent safety validation, recommendation expiry/version checks, authenticated Policy Service client, and security-event persistence for execution/control actions | Add request-rate limiting and tests for malformed/non-finite telemetry, replays, and authentication failures |
| Secrets | `.env`, private keys and generated artifacts are ignored; ACL generation prompts securely and stores only hashes | Run secret scanning and container/dependency scans in CI; rotate all deployment credentials |

## Redis ACL provisioning

Generate a unique ACL file outside the repository and protect it as a secret:

```powershell
python .\security\redis\generate_acl.py C:\secure\rate-limiter\users.acl
```

Set `REDIS_ACL_FILE`, `REDIS_GATEWAY_PASSWORD`, and
`REDIS_MONITOR_PASSWORD` in the protected Compose environment. Set the
Gateway's `REDIS_USERNAME=gateway` and `REDIS_PASSWORD` to the gateway
credential. Configure the Policy Service separately with
`REDIS_USERNAME=policy-service` and its own password. The API applications
must not share Redis credentials. The generator does not print passwords and
refuses to overwrite an existing ACL file.

The Redis ACL grants the Gateway access only to bucket and policy snapshot
keys, and only the commands needed to evaluate the token-bucket script and
read snapshots. The Policy Service can update only policy index/snapshot and
service-config keys. The monitoring user is limited to Redis information and
health commands. The default user is disabled. ACL command restrictions must
be verified against the Redis/Lettuce versions used for deployment before
rollout.

The root Compose Redis port remains bound to `127.0.0.1` for local development;
do not expose it on a public interface. TLS is not enabled for that local-only
Compose connection. Production deployments must use TLS or a private
authenticated network and manage certificates separately.

## Audit storage

Apply `ai-controller/sql/017_create_security_audit_events.sql` after migration
016. Audit records include actor label, tenant/service/resource IDs, event,
outcome, valid source IP, and non-secret metadata. Never put credentials,
authorization headers, JWTs, refresh tokens, or request bodies in `details`.

Security milestone acceptance remains **incomplete** until the remaining
deployment/network tests and dependency/container/secret scans above pass.
