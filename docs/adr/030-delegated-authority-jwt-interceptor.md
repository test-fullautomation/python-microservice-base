# ADR-030: Per-user authorisation via delegated authority service + JWT interceptor

## Status

Proposed

## Date

2026-05-10

## Author

Architecture analysis follow-up.  Reviewed against the
[`taf_repo_proposal`](https://github.boschdevcloud.com/BITS-Test-Automation-Solutions/taf_repo_proposal)
reference.

Companion design docs (offline-readable, with diagrams + Gantt):

- [`consul_auth_architecture.html`](https://github.com/test-fullautomation/python-microservice-base/blob/develop/TA/tmp/consul_auth_architecture.html) (English)
- [`consul_auth_architecture_vi.html`](https://github.com/test-fullautomation/python-microservice-base/blob/develop/TA/tmp/consul_auth_architecture_vi.html) (Tiếng Việt)
- [`consul_auth_implementation_plan.html`](https://github.com/test-fullautomation/python-microservice-base/blob/develop/TA/tmp/consul_auth_implementation_plan.html)
  (English implementation plan)
- [`consul_auth_implementation_plan_vi.html`](https://github.com/test-fullautomation/python-microservice-base/blob/develop/TA/tmp/consul_auth_implementation_plan_vi.html)
  (Vietnamese implementation plan)

## Reviewer

- (pending)

## History

| Date       | Version | Description |
|------------|---------|-------------|
| 2026-05-10 | 1.0     | Initial draft.  Captures the decision to introduce a delegated Authority Service plus a JWT-validating gRPC interceptor; defers Consul Connect to Phase 2. |
| 2026-05-10 | 1.1     | Added three refinements after first review: (1) per-service `public_service` flag for genuine opt-out of JWT enforcement; (2) `--service-style {grpc,http}` flag in `mb-scaffold` so AS is generated through the same toolchain as every other service; (3) JWKS-wait at service startup with health-gated Consul registration so service ordering falls out organically rather than via explicit `depends_on`. |

## Context

The framework currently has **no per-user authorisation story** for
service calls.  Three concrete gaps motivate this ADR:

1. **Consul ACLs gate discovery, not invocation.**  Once a client
   resolves a service through Consul (`GET /v1/health/service/<name>`),
   the gRPC service has no way to authenticate or authorise the caller.
   The user keeps the address and can call again tomorrow without ever
   re-asking Consul.  See *Discovery vs invocation gap* in the
   companion architecture HTML.

2. **AD-group → policy mapping is too coarse.**  The simplest "use AD
   for auth" model maps AD groups to Consul policies in a sidecar.
   This works but makes the AD admin a bottleneck: every project
   member, every scope change, every offboarding requires an AD group
   edit.  We need delegated authority where *our* admin (Bob) can
   grant access to a specific user (Charlie) for a specific service
   without involving corp IT.

3. **Service-to-service auth is a separate problem from human auth.**
   Lumping them together leads to designs that are wrong for both.
   Phase 1 must solve the human path; Phase 2 (Consul Connect) handles
   the service-to-service path.

Existing assets we can build on:

- `BaseServiceSettings` already has a `consul_token` field but it is
  not plumbed end-to-end (the FastAPI bridge and `QConnectBase`
  GrpcClient ignore it).
- `QConnectBase.GrpcClient` can be extended with `auth_endpoint` and
  `consul_token` fields without breaking existing connection types.
- The Manager GUI already has a clean Connect-to-Consul modal that a
  Login button can sit next to.
- Generated services use `grpc.aio` (Python) / `grpc::Server` (C++);
  both expose interceptor extension points that can host a JWT check
  with no changes to handler code.

## Decision

Adopt a **two-layer authorisation model**:

1. **Authority Service** (new, our code) — a small Python + FastAPI
   service that validates a Kerberos ticket against Active Directory,
   looks up the resulting principal in a **local permission database**
   that *we* maintain, and mints two tokens:
   - A **JWT** (signed RS256 by the AS) carrying the user's identity
     plus a `services` claim — the per-service grants — for offline
     verification at each gRPC service.
   - A **Consul ACL token** scoped to the same set of services, so
     the user's catalog discovery is also gated.
2. **JWT interceptor** on every generated service — verifies the JWT
   signature using the AS's published JWKS endpoint, checks standard
   claims (`iss`, `aud`, `exp`), looks up this service's grant in the
   `services` claim, and enforces a per-method scope hierarchy.

The Kerberos identity layer reuses the org's existing AD; the
authorisation layer is owned by us so admins can grant / revoke /
audit per-user, per-service, per-scope without touching AD groups.

### Architecture

```
┌──────────────┐      ┌──────────────┐      ┌──────────────────┐
│  Active      │      │  Authority   │      │  Consul          │
│  Directory   │─────►│  Service     │─────►│  (catalog +ACL)  │
│  (Kerberos)  │ TGT  │  • Kerberos  │      └──────────────────┘
└──────────────┘      │    validator │              ▲
        ▲             │  • Permission│              │ X-Consul-Token
        │             │    DB lookup │              │ (scoped to grants)
        │             │  • JWT issuer│              │
        │ SPNEGO      │  • Consul    │              │
        │             │    token mint│              │
┌──────────────┐      │  • Audit log │      ┌──────────────────┐
│  Windows     │─────►│              │─────►│  gRPC services   │
│  user        │      └──────────────┘      │  + JwtAuth       │
│  (GUI/CLI/   │            │               │    Interceptor   │
│   Robot)     │            │ admin API     └──────────────────┘
└──────────────┘            │ (grant/revoke)
                            ▼
                      ┌──────────────┐
                      │  Permission  │
                      │  DB (SQLite) │
                      └──────────────┘
                            ▲
                            │
                      ┌──────────────┐
                      │  Admin UI    │
                      │  (Bob)       │
                      └──────────────┘
```

### Permission DB schema (canonical)

```sql
CREATE TABLE users (
  id INTEGER PRIMARY KEY,
  email TEXT UNIQUE NOT NULL,        -- canonical identifier
  ntid TEXT UNIQUE,                  -- alias for org-internal lookup
  full_name TEXT,
  enabled INTEGER DEFAULT 1,
  created_at INTEGER NOT NULL
);

CREATE TABLE service_grants (
  id INTEGER PRIMARY KEY,
  user_id INTEGER NOT NULL REFERENCES users(id),
  service TEXT NOT NULL,             -- gRPC FQN, e.g. calc.v1.CalculatorService
  scope TEXT NOT NULL,               -- "read" | "write" | "admin" | custom
  granted_by INTEGER REFERENCES users(id),
  granted_at INTEGER NOT NULL,
  expires_at INTEGER,                -- NULL = no expiry
  UNIQUE(user_id, service, scope)
);

CREATE TABLE roles (
  id INTEGER PRIMARY KEY,
  name TEXT UNIQUE NOT NULL          -- e.g. "Admin", "ServiceOwner"
);

CREATE TABLE user_roles (
  user_id INTEGER REFERENCES users(id),
  role_id INTEGER REFERENCES roles(id),
  PRIMARY KEY (user_id, role_id)
);

CREATE TABLE audit_log (
  id INTEGER PRIMARY KEY,
  ts INTEGER NOT NULL,
  actor TEXT NOT NULL,
  action TEXT NOT NULL,              -- GRANT | REVOKE | LOGIN | DENY
  target TEXT,
  details TEXT                       -- JSON blob
);
```

### JWT shape

```json
{
  "iss":  "https://auth.example.com",
  "aud":  "msb-services",
  "sub":  "charlie@bosch.com",
  "ntid": "chs1bk",
  "iat":  1715421000,
  "exp":  1715421900,
  "jti":  "00000000-0000-0000-0000-000000000000",
  "services": [
    { "name": "calc.v1.CalculatorService", "scope": "write" }
  ]
}
```

`exp` defaults to 15 minutes after `iat`.  `jti` is reserved for the
optional revocation list mechanism in Phase 2 (unused at service-side
JWT verification in Phase 1).

Signed RS256.  Verification at services uses the AS's published
[JWKS](https://datatracker.ietf.org/doc/html/rfc7517) endpoint
(`/.well-known/jwks.json`) cached for ~1 hour.

### Interceptor logic (per call)

1. **Exempt list** — `grpc.health.v1.Health.*` and
   `grpc.reflection.v1alpha.ServerReflection.*` bypass the check
   entirely (Consul TCP-then-gRPC health probes and the bridge's
   reflection enumeration must keep working).
2. **Extract Bearer token** from the `authorization` metadata header.
3. **Verify signature** using the cached JWKS public key.
4. **Check standard claims** — `iss`, `aud`, `exp`.
5. **Find this service's grant** in `claims.services` by name.
6. **Check scope satisfies the method's required scope**
   (per-method map, e.g. `Add` requires `write`).

Failure modes return `UNAUTHENTICATED` (steps 2–4) or
`PERMISSION_DENIED` (steps 5–6).  The handler never runs on rejection.

### Configuration surface (refinements added in v1.1)

Three orthogonal knobs in `BaseServiceSettings` shape every service's
relationship with the auth stack:

```python
class BaseServiceSettings:
    public_service: bool = False              # opt out of JWT enforcement
    auth_endpoint: str = ""                   # AS base URL — required when public_service=False
    auth_jwks_startup_timeout: int = 60       # secs to wait for JWKS at startup
    auth_fail_open_on_startup: bool = False   # emergency hatch (NEVER set in prod)
```

Behaviour matrix:

| `public_service` | `auth_endpoint` | Service startup behaviour |
|---|---|---|
| `False` (default) | set | `JwtAuthInterceptor` installed; service polls `<auth_endpoint>/.well-known/jwks.json` at startup; **registers in Consul as healthy only after JWKS is fetched**; if fetch fails after `auth_jwks_startup_timeout`, service exits non-zero (Nomad restarts with backoff). |
| `False` (default) | empty | **Fail-fast at startup**: "service requires auth but no `auth_endpoint` configured".  Misconfiguration; no service starts in this state. |
| `True` | (any) | `JwtAuthInterceptor` **not** installed; service starts independently of AS; `WARNING` logged; audit log records "service `<name>` started in PUBLIC mode by `<deployer>`"; Consul registration carries a `public=true` tag so the GUI can show a 🌐 icon. |

The `auth_fail_open_on_startup` flag is an explicit emergency-recovery
escape hatch: when AS is unreachable for an extended period, an operator
can set it per-service to start the service anyway and have it return
`UNAVAILABLE` to all calls until JWKS arrives.  Documented as
operator-only; never the default.

### AS itself uses the scaffold (refinement added in v1.1)

AS is generated by `mb-scaffold` like any other platform service, via a
new `--service-style {grpc,http}` flag:

```bash
mb-scaffold --name Authority --language python --service-style http \
    --public --gen-nomad
```

The `http` flavor emits a FastAPI skeleton instead of a `ServiceRunner`
gRPC server, but reuses everything else: `BaseServiceSettings`,
`ConsulRegistration`, healthcheck endpoint, `.nomad.hcl` job, README
and build scripts.  The `--public` flag pre-sets `public_service=True`
in the generated settings.

Benefits:

- AS deploys, registers, monitors, and rotates exactly like every other
  service — no special-case operational story.
- The `--service-style http` flavor is reusable for future HTTP-only
  services (webhook receivers, admin tools, dashboards).
- The framework eats its own dog food, proving the scaffold can produce
  a real production service.

### Service ordering falls out organically (refinement added in v1.1)

No explicit `depends_on` declarations needed in `.nomad.hcl`.  Because
every service with `auth_endpoint` set polls JWKS at startup and only
registers in Consul as healthy *after* the fetch succeeds, the
dependency order resolves naturally:

```
Consul → AS (public, no JWKS dep) → all other services (wait for JWKS → healthy)
```

If AS is down for a long time:

- Existing services with valid JWTs keep working (JWKS cached at services).
- New tokens cannot be issued.
- New services attempting to start fail-fast after the JWKS timeout; Nomad
  retries them automatically with backoff.

This is the correct behaviour: a system that requires auth and cannot
verify auth should not accept requests.

### Revocation semantics

- **Permission DB** — immediate (`DELETE` row + `INSERT audit_log`).
- **Consul token** — immediate (AS calls `DELETE /v1/acl/token/<accessor>`).
- **JWT in user's pocket** — *delayed until expiry* (default 15 min).

This is the standard JWT trade-off.  We accept it for Phase 1 and
defer revocation lists / force-logout to Phase 2.  The admin UI
must show users *"Revocation effective within 15 minutes"* to set
the right expectation.

### Phased rollout

Phase 1 (this ADR):

- Authority Service (Kerberos + permission DB + JWT/Consul-token issuance + admin API)
- Admin UI
- `consul_token` plumbed across FastAPI bridge, `QConnectBase` GrpcClient, Manager GUI
- `JwtAuthInterceptor` for Python + C++ services
- Two new MSB_xxxx tests (token-gated happy path + revocation)

Phase 2 (separate ADR when triggered):

- Consul Connect for service-to-service mTLS + intentions
- Vault PKI for cert issuance
- Postgres backend (HA Authority Service)
- Revocation list + force-logout
- Self-service access requests

## Consequences

### Positive

- **Per-user attribution in audit logs** (`alice did X`, not
  `service-account did X`).  `audit_log.actor` answers "who" cleanly.
- **Zero AD-admin involvement** for routine grants and revokes.  Bob
  manages access through our UI; AD remains the source of truth for
  identity but not for project-level authorisation.
- **Closes the discovery-vs-invocation gap** for human callers.
  Consul-token scopes discovery, JWT scopes invocation; both anchored
  in the same DB rows.
- **Stateless verification at services.**  After fetching the JWKS
  once, services validate JWTs offline with no AS round trip.  A
  10,000-RPS service costs zero additional AS traffic.
- **Standards-based.**  RS256 JWT + JWKS are RFCs (7515, 7517, 7519);
  any future client / library / language understands the wire format.
- **Per-user, per-service, per-scope granularity** is finer than
  AD-group-based models, with native support for time-bound grants
  via `expires_at`.
- **Reuses MicroserviceBase house language** (Python + FastAPI) — no
  new language for the platform team.
- **Secure-by-default opt-out for public services** — `public_service`
  flag is False unless explicitly set; deploying a genuinely public
  service is a deliberate, audited action rather than a config typo.
- **AS deploys like any other service** — no special-case operational
  story; the framework eats its own dog food.  The new
  `--service-style http` flavor of `mb-scaffold` is reusable for any
  future HTTP-only service.
- **Service ordering is organic** — no explicit `depends_on` needed;
  JWKS-wait at startup means whichever service finds AS first goes
  ready first, AS itself comes up at its own pace, and Consul-driven
  health gating keeps unready services out of discovery.

### Negative

- **New service to operate** — Authority Service is a new dependency
  with its own keytab, RSA keypair, SQLite backup, monitoring story.
- **Kerberos is unforgiving** — clock skew >5 min, SPN typos, KDC
  outages all manifest as cryptic 401s.  Documented in the ops
  runbook; mitigated by NTP requirement + clear error messages.
- **Revocation latency = JWT TTL** (default 15 min) for already-issued
  tokens.  Acceptable for Phase 1; addressed in Phase 2 if needed.
- **Browser SPNEGO config required** — users on Chrome / Edge / Firefox
  need the AS hostname added to their negotiate-auth allowlist.
  Documented.
- **Code commitment.**  ~1500–2500 LoC across AS + UI + CLI, plus
  ~200–400 LoC in MicroserviceBase plumbing (`Settings` field,
  interceptors, GUI Login, Robot config field).  Not throwaway.
- **In-flight streaming RPCs are not interrupted by revocation.**  The
  interceptor runs once at stream start.  Acceptable for Phase 1
  because we don't ship sensitive streaming RPCs; documented as a
  known limitation.
- **`--service-style {grpc,http}` adds scaffold complexity.**  Two
  template families to maintain in `mb-scaffold` (gRPC and HTTP).
  Mitigated by the HTTP flavor reusing every shared file (settings,
  Consul reg, Nomad job, README) — only the language-specific source
  layout differs.
- **Fail-fast on JWKS timeout may surprise dev environments.**  A
  service started without AS reachable will exit and Nomad will restart
  it.  Documented in the runbook; the `auth_fail_open_on_startup` hatch
  exists for emergency-recovery scenarios.

### Neutral

- **First-admin bootstrap** is a one-shot CLI command
  (`auth-admin grant-role --email bob@bosch.com --role Admin`).
  Documented; not a recurring concern.
- **SQLite single-file storage** is a deliberate choice for Phase 1
  speed.  Trivial to migrate to Postgres in Phase 2 (`alembic`-managed
  schema is identical).
- The Authority Service runs as a single instance in Phase 1.  If it
  goes down, *new* logins fail but *existing* JWTs keep working until
  expiry — graceful degradation, not a hard outage.

## Alternatives Considered

### 1. AD groups → Consul policies via Kerberos sidecar (Deferred)

A Kerberos sidecar validates the user's ticket and, based on their
AD group memberships, mints a Consul ACL token bound to the
corresponding policies.  No local permission DB.

Deferred (used as a degenerate special case of this ADR's design)
because:
- Every project membership change requires an AD admin to edit a
  group, slowing onboarding and increasing inter-team friction.
- Time-bound grants ("Charlie can call inventory until 2026-06-01")
  require AD group lifecycle automation that doesn't exist locally.
- Audit answers "alice was in group X" rather than "Bob granted alice
  on 2026-05-10" — fuzzy attribution.
- The local permission DB in this ADR's design *can* mirror AD groups
  later if needed, so this approach remains a valid Phase 2 evolution
  for orgs that prefer central-IT-managed authorisation.

### 2. OIDC via Azure AD or AD FS (Deferred — pick at deployment time)

Configure Consul's OIDC auth method against Azure AD / AD FS;
browser-based SSO flow replaces the SPNEGO handshake.

Deferred to deployment-time decision, not architectural rejection:
- If the deployment environment has Azure AD or AD FS reachable, the
  Authority Service can use OIDC instead of SPNEGO for the identity
  layer.  Everything downstream (permission DB, JWT issuance, gRPC
  interceptor) is identical.
- For air-gapped environments without OIDC IdP available, the
  Kerberos path in this ADR is the canonical answer.
- The HTML companion docs include both flows side-by-side.

### 3. mTLS user certificates (Deferred to Phase 2)

Issue short-lived X.509 client certificates per user; services
identify the caller from the cert CN/SAN.

Deferred because:
- Operationally heavier (cert rotation, CA management, browser cert
  imports for the GUI).
- Vault PKI is the standard backing CA, adding a new dependency
  before we have a documented compliance need that demands it.
- Compatible with the JWT model in this ADR — a Phase 2 layering
  could use mTLS for transport identity and JWT for fine-grained
  scope without touching the permission DB.

### 4. Consul Connect / Envoy service mesh (Deferred to Phase 2)

Each service gets an Envoy sidecar; mTLS between sidecars is
enforced via per-service identities issued by Consul, with intentions
controlling who can talk to whom.

Deferred because:
- Solves *service-to-service* auth, which is a separate problem from
  the *human-to-service* problem this ADR addresses.
- Adds ~40 MB RAM per service plus the operational cost of running a
  service mesh.
- The phased recommendation in the architecture doc is to layer
  Consul Connect on top of this ADR's design when service-to-service
  traffic appears.

### 5. Custom HTTP-header trust ("just trust the user header") (Rejected)

Some internal tools accept a header like `X-User-Email` set by a
trusted reverse proxy; the service trusts whatever the proxy sends.

Rejected because:
- One misconfigured route bypasses authentication entirely.
- No auditable signing — services can't verify the header wasn't
  forged upstream.
- Indistinguishable from "no auth" to a security audit.

## References

- Companion design doc:
  [`D:\Project\TA\tmp\consul_auth_architecture.html`](https://github.com/test-fullautomation/python-microservice-base/blob/develop/TA/tmp/consul_auth_architecture.html)
- Companion implementation plan:
  [`D:\Project\TA\tmp\consul_auth_implementation_plan.html`](https://github.com/test-fullautomation/python-microservice-base/blob/develop/TA/tmp/consul_auth_implementation_plan.html)
- ADR-022: Nomad orchestrator integration (provides the per-process
  identity for service-account tokens)
- ADR-023 / 024: multi-node Consul / Nomad cluster (target topology
  this auth model layers on top of)
- ADR-029: Robot Framework as primary test client (the
  `QConnectBase.GrpcClient` extension in this ADR consumes the JWT
  via a new `auth_endpoint` config field)
- RFC 7515 (JWS), RFC 7517 (JWK / JWKS), RFC 7519 (JWT)
- HashiCorp Consul ACL system:
  <https://developer.hashicorp.com/consul/docs/security/acl>
- Existing relevant source files:
  - `MicroserviceBase/runtime/settings.py` — `BaseServiceSettings.consul_token` (already exists; needs `auth_endpoint` field added)
  - `MicroserviceBase/adapters/ui_bridge/fastapi_bridge.py` — needs `consul_token` plumbed through `/api/grpc/*` and `/api/consul/*`
  - `QConnectBase/grpc/grpc_client.py` — needs `consul_token` and `auth_endpoint` fields in `GrpcClientConfig`
  - `MicroserviceBase/MicroserviceManagerGUI/web/js/app.js` — needs Login button + sessionStorage token handling
