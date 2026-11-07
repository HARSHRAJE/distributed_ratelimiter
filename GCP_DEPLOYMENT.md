# GCP demo deployment

This demo runs in project `bold-mantis-463806-q5`, region `us-central1`, using
Cloud Run, Cloud SQL, and Memorystore. It does not use a VM.

## Deployed services

All five Cloud Run services are ready. The Gateway is public; the other
services use internal ingress.

| Service | URL |
|---|---|
| Gateway (public entry point) | https://gateway-607653541134.us-central1.run.app |
| Auth Service (internal) | https://auth-service-607653541134.us-central1.run.app |
| Orders Service (internal) | https://orders-service-607653541134.us-central1.run.app |
| Policy Service (internal) | https://policy-service-607653541134.us-central1.run.app |
| AI Controller API (internal) | https://ai-controller-api-607653541134.us-central1.run.app |

The Gateway health endpoint is
[`/actuator/health`](https://gateway-607653541134.us-central1.run.app/actuator/health).
It reports `UP` when checked.

Only the Gateway URL is intended for Postman from the public internet. The
other listed URLs use internal ingress; calling them directly from Postman
returns a Cloud Run 404. Use the Gateway URL for registration, login, and
Orders requests. Its Auth route forwards `/api/v1/auth/**` to the internal
Auth Service.

The Gateway and AI Controller use Direct VPC egress with all traffic routed
through the VPC, and Private Google Access is enabled on the `us-central1`
default subnet. This allows them to call other Cloud Run services configured
with internal ingress.

## Automatic deployment on code changes

The workflow in
[`.github/workflows/deploy-gcp.yml`](./.github/workflows/deploy-gcp.yml)
runs Java and Python tests on pull requests and pushes affecting an
application service. A successful push to `main` builds and pushes
SHA-tagged container images, updates all five Cloud Run services, and checks
Gateway health. A manual run is also available in GitHub Actions for the
`main` branch.

GitHub Actions authenticates to Google Cloud using Workload Identity
Federation; no service-account JSON key or GitHub secret is used. The GCP
identity is restricted to this repository's `main` branch. The configured
provider is
`projects/607653541134/locations/global/workloadIdentityPools/github-actions/providers/github`,
and the deploy service account is
`github-actions-deployer@bold-mantis-463806-q5.iam.gserviceaccount.com`.
The deployer has Artifact Registry write access, Cloud Run deploy access,
permission to use enabled GCP APIs, and permission to act as the five existing
runtime service accounts.

After committing and pushing application changes to `main`, check the
repository's **Actions** tab for **Test and deploy to Cloud Run**. All tests
must pass before image publishing and deployment begin. Updating a service's
image retains its existing Cloud Run environment variables, secrets, ingress,
scaling, and VPC configuration. Changes to CI credentials or GCP roles require
an authorized administrator; do not add service-account keys to GitHub.

## Postman: public end-to-end smoke test

Only the Gateway is public. In Postman, create an environment with:

| Variable | Initial value |
|---|---|
| `baseUrl` | `https://gateway-607653541134.us-central1.run.app` |
| `accessToken` | *(leave blank until login)* |
| `tenantId` | *(the tenant UUID provisioned for your test user)* |
| `testEmail` | *(your registered test-user email)* |
| `testPassword` | *(your test-user password)* |

Use `{{baseUrl}}` in request URLs. Do not save real passwords or tokens in a
shared Postman workspace or exported collection.

### A. Check Gateway and authentication

1. **Gateway health** — `GET {{baseUrl}}/actuator/health`, no authorization.
   Expect `200` and `{"groups":["liveness","readiness"],"status":"UP"}`.
2. **Register a test user** — `POST {{baseUrl}}/api/v1/auth/register`,
   Body → raw → JSON:

   ```json
   {
     "email": "{{testEmail}}",
     "password": "{{testPassword}}"
   }
   ```

   Expect `201`. Password must be 12–72 characters. Registration creates a
   user only; it does not create a tenant or tenant membership. If the user
   already exists, skip registration. Use the Gateway `baseUrl`, not the
   internal Auth Service URL; direct requests to Auth from a public
   workstation return Cloud Run 404.
3. **Provisioning prerequisite** — an authorized operator must create or
   select a tenant, add a membership for this user, and configure active
   `orders-service` policies as described below. Until then, login or the
   rate-limited orders route cannot complete successfully. The Google Cloud
   account used to deploy is not automatically an application user.
4. **Log in** — `POST {{baseUrl}}/api/v1/auth/login`, Body → raw → JSON:

   ```json
   {
     "email": "{{testEmail}}",
     "password": "{{testPassword}}",
     "tenantId": "{{tenantId}}"
   }
   ```

   Expect `200`. The response contains `accessToken`, `expiresIn`, `userId`,
   `tenantId`, `tenantKey`, and `roles`. Save the token to the environment
   using this Postman **Tests** script:

   ```javascript
   const body = pm.response.json();
   pm.environment.set("accessToken", body.accessToken);
   ```

   Login also sets the HttpOnly `refresh_token` cookie. Postman should retain
   it in its cookie jar for the Gateway host.
5. **Current user** — `GET {{baseUrl}}/api/v1/auth/me`, Authorization → Bearer
   Token → `{{accessToken}}`. Expect `200` with the user and selected tenant.
6. **Refresh session** — `POST {{baseUrl}}/api/v1/auth/refresh`, no JSON body.
   Keep Postman's cookie jar enabled. Expect `200`; save the new
   `accessToken` with the same Tests script because access tokens expire.
7. **Logout** — `POST {{baseUrl}}/api/v1/auth/logout`, with the refresh cookie.
   Expect `204`; this revokes the refresh token. Log in again before
   continuing.

Auth routes also include `POST /api/v1/auth/select-tenant` (Bearer token plus
refresh cookie, JSON `{"tenantId":"<another-membership-tenant-uuid>"}`), which
rotates the session into another tenant for which the user has membership.

### B. Test rate-limited Orders calls

Set Authorization → Bearer Token → `{{accessToken}` on each request:

| Method and URL | Body | Expected result |
|---|---|---|
| `GET {{baseUrl}}/api/orders` | None | `200`, `Orders service is working`, plus `X-RateLimit-Remaining-*` headers |
| `POST {{baseUrl}}/api/orders` | None | `200`, `Order created successfully`, plus remaining-quota headers |

The three quota headers are `X-RateLimit-Remaining-Tenant`,
`X-RateLimit-Remaining-Route`, and `X-RateLimit-Remaining-Service`. After the
corresponding bucket is exhausted, expect `429 RATE_LIMIT_EXCEEDED` and a
`Retry-After` header; wait for refill before testing again. An unmapped or
missing policy fails closed (typically `503`), and a disabled policy returns
`403 POLICY_DISABLED`. An unauthenticated request should return `401`.

Use only a few manual requests for this demo. Avoid Postman Runner loops,
stress tests, or large request counts: Cloud SQL and Memorystore are small
demo tiers and have ongoing costs.

## Other API endpoints and access

The following services have internal Cloud Run ingress. Their `run.app` URLs
are not public Postman endpoints, and the Gateway does not proxy these paths.
Do not change ingress to public just for testing. `gcloud run services proxy`
also cannot reach an internal-only service from a workstation outside its VPC.

### Policy Service (internal)

The REST API root is `/api/v1`. It requires an application JWT with an
appropriate role; policy writes also enforce service-level authorization.

| Method and path | Description |
|---|---|
| `POST /services` | Register a service; `SUPER_ADMIN` |
| `GET /services` | List services; `SUPER_ADMIN` |
| `GET /services/{id}` | Get a service by UUID; `SUPER_ADMIN` or `SERVICE_ADMIN` |
| `GET /services/by-key/{serviceKey}` | Get a service by key; `SUPER_ADMIN` or `SERVICE_ADMIN` |
| `PUT /services/{id}/configuration` | Update global capacity/refill configuration; `SUPER_ADMIN` |
| `PUT /services/{id}/adaptive-configuration` | Submit an adaptive config change; requires `X-Policy-Service-Key` |
| `GET /services/{id}/configuration/executions/{executionId}` | Check adaptive config execution; requires `X-Policy-Service-Key` |
| `PUT /services/{id}/adaptive-rollback` | Submit an adaptive rollback; requires `X-Policy-Service-Key` |
| `GET /services/{id}/configuration/rollbacks/{rollbackId}` | Check rollback status; requires `X-Policy-Service-Key` |
| `PUT /services/by-key/{serviceKey}/adaptive-control` | Change adaptive control settings; requires `X-Policy-Service-Key` |
| `PUT /services/execution-control` | Change execution kill switch; requires `X-Policy-Service-Key` |
| `GET /services/by-key/{serviceKey}/effective-configuration` | Read effective Redis config; requires `X-Policy-Service-Key` |
| `POST /policies` | Create tenant/route policy; `SUPER_ADMIN` or `SERVICE_ADMIN` |
| `GET /policies?serviceKey=...&tenantId=...&routeId=...` | Find a policy by scope |
| `GET /policies/{policyId}` | Get a policy |
| `PUT /policies/{policyId}` | Update a policy |
| `PATCH /policies/{policyId}/activate` | Activate a policy |
| `PATCH /policies/{policyId}/deactivate` | Deactivate a policy |
| `POST /policies/{policyId}/rollback/{version}` | Roll back a policy to a version |
| `GET /policies/{policyId}/versions` | List policy versions |
| `GET /policies/{policyId}/versions/{version}` | Get one version |
| `GET /policies/{policyId}/audit` | View policy audit history |

The Gateway needs active policies for service key `orders-service` and the
tenant UUID used at login. Configure the `get-orders` route for
`GET /api/orders` and `create-order` for `POST /api/orders`. The service,
tenant, and policies must be synchronized before sending Orders traffic.
Adaptive-execution endpoints under `/services` are for the AI Controller and
require `X-Policy-Service-Key`; they are not part of the manual Postman smoke
test. Adaptive configuration/rollback paths are also subject to execution
state and version checks.

For an authorized operator with access to the internal Policy Service, the
minimum setup is:

1. If `orders-service` is not already registered, send
   `POST /api/v1/services` with an operator JWT having `SUPER_ADMIN`:

   ```json
   {
     "serviceKey": "orders-service",
     "globalCapacity": 100,
     "globalRefillRate": 20.0,
     "hardMaxRefillRate": 100.0
   }
   ```

   These are illustrative demo values, not recommended production limits.
   Keep global refill rate at or below the hard maximum. If the service
   already exists, use `GET /api/v1/services` instead of creating it again.
2. For each of `get-orders` and `create-order`, send `POST /api/v1/policies`
   with an operator JWT having `SERVICE_ADMIN` or `SUPER_ADMIN`. Replace the
   tenant UUID and tune capacities/refill rates for your demo:

   ```json
   {
     "serviceKey": "orders-service",
     "tenantId": "{{tenantId}}",
     "routeId": "get-orders",
     "tenantCapacity": 20,
     "tenantRefillRate": 5.0,
     "routeCapacity": 10,
     "routeRefillRate": 2.0,
     "minRefillRate": 0.1,
     "maxRefillRate": 20.0,
     "createdBy": "postman-demo-operator"
   }
   ```

   Repeat with `"routeId": "create-order"`. Policy creation creates an active
   initial version and publishes it for Redis reconciliation. Allow a short
   time for synchronization, then test `GET /api/v1/policies` with the
   `serviceKey`, `tenantId`, and route ID query parameters.

This deployment does not expose a public admin API for provisioning tenants,
memberships, services, or policies. An authorized operator must provision
them through the internal service/database path. Never put database
credentials, Secret Manager values, internal API keys, or administrator keys
in a shared Postman collection.

### AI Controller API (internal)

The API root is `/api/v1`. Its interactive schema is `/docs` when accessed
from an authorized network. Except for `GET /health`, its API routers require
`X-Internal-API-Key`. Some execution and circuit-breaker controls additionally
require `X-Admin-API-Key`. These secrets are not the user's login token.

| Endpoint group | Main endpoints | Purpose |
|---|---|---|
| Health | `GET /health` | Liveness check |
| Telemetry | `GET /telemetry/status`, `GET /telemetry/latest/{serviceKey}`, `GET /telemetry/history/{serviceKey}` | Collection state and telemetry |
| Forecast | `POST /forecast/{serviceKey}`, `GET /forecast/latest/{serviceKey}`, `GET /forecast/history/{serviceKey}`, `GET /forecast/accuracy/{serviceKey}` | Generate and inspect forecasts |
| Recommendations | `POST /recommendations/evaluate/{serviceKey}`, `GET /recommendations/{serviceKey}/latest`, `GET /recommendations/{serviceKey}/history`, `PATCH /recommendations/{id}/accept`, `PATCH /recommendations/{id}/reject` | Generate and review recommendations |
| Safety | `POST /safety/validate/{recommendationId}`, `GET /safety/{recommendationId}/latest`, `GET /safety/{recommendationId}/history` | Validate recommendations against safety constraints |
| Shadow | `POST /shadow/evaluate/{serviceKey}`, `GET /shadow/{serviceKey}/latest`, `GET /shadow/{serviceKey}/history`, `GET /shadow/{serviceKey}/comparison` | Compare proposed policies without changing live policy |
| Execution | `POST /execution/{recommendationId}`, `GET /execution/{executionId}`, `GET /execution/{serviceKey}/history`, `POST /execution/{serviceKey}/enable`, `POST /execution/{serviceKey}/disable`, `POST /execution/emergency/activate`, `POST /execution/emergency/deactivate` | Guarded adaptive execution and its status |
| Rollback | `POST /rollback/evaluate/{serviceKey}`, `POST /rollback/execute/{executionId}`, `GET /rollback/{serviceKey}/history`, `GET /rollback/{rollbackId}` | Evaluate and inspect rollback |
| Circuit breaker | `GET /circuit-breaker/{serviceKey}`, `GET /circuit-breaker/{serviceKey}/history`, `POST /circuit-breaker/{serviceKey}/open`, `POST /circuit-breaker/{serviceKey}/reset` | Breaker status and operator controls |
| Tenant allocation | `PUT /allocations/{serviceKey}/tenants`, `GET /allocations/{serviceKey}/tenants`, `POST /allocations/evaluate/{serviceKey}`, `GET /allocations/{serviceKey}/latest`, `GET /allocations/{serviceKey}/history` | Configure/evaluate tenant allocations |
| Route allocation | `PUT /allocation/routes/{serviceKey}/configs`, `POST /allocation/routes/{serviceKey}/evaluate`, `GET /allocation/routes/{serviceKey}`, `GET /allocation/routes/{serviceKey}/history`, `GET /allocation/routes/{serviceKey}/comparison` | Configure/evaluate route allocations |
| SLA | `PUT /sla/{serviceKey}/tenants`, `GET /sla/{serviceKey}/tenants`, `GET /sla/{serviceKey}/tenants/{tenantId}`, `POST /sla/{serviceKey}/evaluate`, `GET /sla/{serviceKey}/compliance`, `GET /sla/{serviceKey}/allocation-history` | Configure SLA guarantees and inspect compliance |
| Benchmarks | `POST /benchmarks/run`, `GET /benchmarks/{runId}`, `GET /benchmarks/{runId}/results`, `GET /benchmarks/history`, `GET /benchmarks/compare` | Submit and inspect benchmarks |
| Chaos experiments | `POST /chaos/experiments`, `GET /chaos/experiments/history`, `GET /chaos/experiments/{experimentId}`, `GET /chaos/experiments/{experimentId}/results` | Controlled experiments; requires separately configured safe test environment |

The benchmark and chaos endpoints should not be used against a live/shared
demo target. Benchmarking needs its worker and target configuration; chaos
testing is disabled unless an isolated test environment is explicitly
configured. The collection and forecast workers were not deployed, so
continuous telemetry, forecasts, and dependent workflows should not be
expected to have data in this deployment.

## Managed data services

- Cloud SQL: PostgreSQL 17, `db-f1-micro`, 10 GiB SSD, private IP.
- Memorystore: Basic tier, 1 GiB Redis 7.2, private networking, AUTH, and
  server-authenticated TLS.
- Application credentials and signing keys are stored in Secret Manager.

Cloud Run services are configured to scale to zero and use small maximum
instance counts. Cloud SQL and Memorystore have ongoing costs even when the
application is idle. These settings are for a low-cost demo, not production.

## Not deployed

The continuous collection and forecast workers, benchmark worker, Redis
Exporter, Prometheus, and Grafana are not deployed. The workers require
always-running compute; the monitoring stack requires additional services and
persistent storage. They were omitted to follow the selected lowest-cost
option.

## Cleanup

These commands permanently delete the demo database and Redis instance:

```powershell
gcloud run services delete gateway auth-service orders-service policy-service ai-controller-api --region=us-central1 --project=bold-mantis-463806-q5 --quiet
gcloud sql instances delete rate-limiter-demo --project=bold-mantis-463806-q5 --quiet
gcloud redis instances delete rate-limiter-demo --region=us-central1 --project=bold-mantis-463806-q5 --quiet
```

Review Secret Manager and Artifact Registry afterward if you also want to
remove stored credentials and container images. Keep the private service
networking configuration if other resources in the project use it.
