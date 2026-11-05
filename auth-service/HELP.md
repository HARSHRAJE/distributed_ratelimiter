# Auth Service

The Auth Service uses the shared PostgreSQL database and requires an RS256
PKCS#8 private key and matching X.509 public key. Keep both keys outside the
repository; only the Auth Service should have access to the private key.

## Database setup

From the repository root, apply the schema once:

```powershell
Get-Content .\auth-service\src\main\resources\db\create_auth_schema.sql -Raw |
  docker compose exec -T postgres psql -v ON_ERROR_STOP=1 -U rate_limiter_app -d rate_limiter
```

## Local key setup

Generate a local development key pair outside the repository. The helper uses
the JDK and refuses to overwrite an existing key pair:

```powershell
$keyDirectory = Join-Path $HOME '.adaptive-rate-limiter\keys'
java .\auth-service\scripts\GenerateRsaKeys.java $keyDirectory

$env:AUTH_PRIVATE_KEY_LOCATION = "file:$((Join-Path $keyDirectory 'auth-private.pem') -replace '\\','/')"
$env:AUTH_PUBLIC_KEY_LOCATION = "file:$((Join-Path $keyDirectory 'auth-public.pem') -replace '\\','/')"
```

Use a managed key store and restrict private-key file permissions in production.
Serve both services over HTTPS in production and set
`AUTH_REFRESH_COOKIE_SECURE=true`.

## Local run

The Auth Service and Gateway use the same public key, issuer, and audience:

```powershell
# Run from the repository root.
$env:DB_PASSWORD = (Get-Content .\.env | Where-Object { $_ -match '^POSTGRES_PASSWORD=' } | Select-Object -First 1) -replace '^POSTGRES_PASSWORD=', ''
$env:JAVA_TOOL_OPTIONS = '-Duser.timezone=UTC'
.\gateway\gradlew.bat -p .\auth-service bootRun
```

Set `AUTH_PUBLIC_KEY_LOCATION` in the Gateway environment to the same public
key path before starting it.

## Invite-only tenant onboarding

Registration creates a user only. An administrator provisions tenants and
memberships. After registering, use the returned user UUID to create a
membership in an existing tenant:

```sql
INSERT INTO tenants (id, tenant_key, name)
VALUES ('<tenant-uuid>', '<tenant-key>', '<tenant-name>');

INSERT INTO tenant_memberships (id, user_id, tenant_id, role)
VALUES (
    gen_random_uuid(),
    '<registered-user-uuid>',
    '<tenant-uuid>',
    'TENANT_ADMIN'
);
```

Login and tenant selection accept the tenant UUID. Access tokens contain the
tenant key in `tenant_id` (for matching policy tenant identifiers), the UUID
in `tenant_uuid`, and the membership role in `roles`.

The refresh token is returned only as an HttpOnly, SameSite=Strict cookie.
Access tokens are short-lived (15 minutes); refresh tokens rotate for up to
seven days, and reuse of a revoked refresh token revokes all active refresh
tokens for that user.
