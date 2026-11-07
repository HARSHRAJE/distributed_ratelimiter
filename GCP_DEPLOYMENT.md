# GCP demo deployment

This demo runs in project `bold-mantis-463806-q5`, region `us-central1`, using
Cloud Run, Cloud SQL, and Memorystore. It does not use a VM.

## Deployed services

All five Cloud Run services are ready. The Gateway is public; the other
services use internal ingress.

| Service | URL |
|---|---|
| Gateway | https://gateway-y7qqiwucgq-uc.a.run.app |
| Auth Service | https://auth-service-y7qqiwucgq-uc.a.run.app |
| Orders Service | https://orders-service-y7qqiwucgq-uc.a.run.app |
| Policy Service | https://policy-service-y7qqiwucgq-uc.a.run.app |
| AI Controller API | https://ai-controller-api-y7qqiwucgq-uc.a.run.app |

The Gateway health endpoint is
[`/actuator/health`](https://gateway-y7qqiwucgq-uc.a.run.app/actuator/health).
It reports `UP` when checked.

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
