# Security Posture

This document records the threat model for the EU Border Risk Profiler
and the controls in place to mitigate it. It is deliberately concise —
the system has a small attack surface and the underlying data is
public — but the analysis follows Microsoft's STRIDE taxonomy so the
reasoning is auditable. Operators deploying this service should read
this page before exposing any of its endpoints to the public Internet.

## Reporting a vulnerability

Please open a private security advisory on the GitHub repository or
contact the maintainer. Do not file a public issue for security
findings. We aim to acknowledge reports within 72 hours.

## Assets

| Asset | Sensitivity | Notes |
|-------|-------------|-------|
| **Eurostat raw data in `asylum_data`** | Low | Public data redistributed under the Eurostat re-use policy. Aggregation level is country/month, no personal data. |
| **Trained models in `model_registry`** | Low | Pickled scikit-learn artifacts; reproducible from the data. |
| **Predictions in `risk_predictions`** | Low | Derived numerical scores. Politically sensitive in framing but contains no personal data. |
| **API endpoints (`/api/v1/...`)** | Medium | The API is the only public read surface. Throttling and auth gates apply here. |
| **Streamlit dashboard (`/`)** | Medium | Same data, presented to humans. |
| **Database credentials** | High | If leaked, full read/write on every asset. |
| **`API_KEY` (when set)** | Medium | Single shared secret protecting the API. |

## Trust boundaries

```
[ Internet ] ──┬── 80/443  ── [ reverse proxy ] ── [ dashboard (Streamlit) ] ──┐
               │                                                                │
               └── 8000    ── [ reverse proxy ] ── [ api_service (FastAPI) ] ──┤
                                                                                │
                                                  [ data_harvester ] ──────────┤
                                                                                │
                                                  [ risk_predictor ] ──────────┤
                                                                                │
                                                                  [ PostgreSQL ]
                                                                  (loopback only)
```

The reverse proxy (Traefik on Dokploy, equivalent on other deployments)
terminates TLS and is responsible for HSTS, modern cipher suites, and
rate limits at the network edge. Inside the Docker network, services
communicate in clear over a private bridge. The PostgreSQL port is
bound to `127.0.0.1` on the host so it is unreachable from the public
network.

## STRIDE analysis

### Spoofing identity

- **Threat.** An anonymous caller queries the API at scale, scrapes
  the dataset, or impersonates the bundled dashboard.
- **Mitigation.**
  - Optional `X-API-Key` authentication ([ADR-004](adr/004-optional-api-key-auth.md))
    can be enabled by setting an environment variable. When enabled,
    every protected endpoint rejects requests without a matching key.
  - `/health` remains unauthenticated by design so external monitoring
    keeps working.
- **Open issue.** The single-key model does not distinguish consumers.
  See ADR-004's "Migration path" section if multi-tenant identity
  becomes a requirement.

### Tampering with data

- **Threat.** An attacker modifies asylum or prediction data in flight
  or at rest.
- **In transit:** the API only exposes read endpoints; there is no
  user-facing write path. Inter-service traffic is on a private Docker
  network. TLS termination at the reverse proxy protects external
  traffic.
- **At rest:** only the `data_harvester`, `risk_predictor` and
  `api_service` containers connect to PostgreSQL. The harvester is
  the sole writer of `asylum_data` and uses an atomic staging swap
  ([ADR-002](adr/002-staging-table-for-atomic-harvest.md)) so a
  partially-written table is never observable.
- **Open issue.** No row-level checksums or signed snapshots. A
  database-level write performed by a credentialed actor would be
  invisible to clients. Acceptable at this maturity given the data
  is public and the deployment surface is small.

### Repudiation

- **Threat.** A consumer denies having queried specific data.
- **Mitigation.** Reverse-proxy access logs record `(timestamp, IP,
  request line, response code)` for every external call. The API
  emits structured logs for protected-endpoint access. With the
  shared `X-API-Key` model the logs cannot attribute calls to a
  specific consumer; introducing a `consumers` table (see ADR-004
  migration path) would close that gap.

### Information disclosure

- **Threat.** Confidential data is exposed.
- **Analysis.** The system processes only public Eurostat aggregates;
  no personal data, no operational law-enforcement information, no
  intelligence material. The most sensitive asset is therefore the
  database password itself, which would grant write access. It is
  passed via environment variables and never logged. The Streamlit
  XSRF protection is enabled to prevent third-party origins from
  embedding or replaying dashboard interactions.
- **Open issue.** Logs may incidentally include header values during
  exception handling. The current code paths do not log request
  headers, but this should be enforced by a structured-logging
  policy in a future iteration.

### Denial of service

- **Threat.** An attacker exhausts CPU, memory, database connections,
  or open Tornado workers (Streamlit) and renders the service
  unavailable.
- **Mitigation.**
  - The reverse proxy is expected to enforce a baseline rate limit at
    the edge. On Dokploy this is the recommended Traefik middleware.
  - PostgreSQL connections are pooled by SQLAlchemy with
    `pool_pre_ping=True`; a slow database does not exhaust the
    application thread pool.
  - The harvester uses HTTP `HEAD` against Eurostat to detect
    unchanged datasets, which limits outbound bandwidth and load.
- **Open issue.** No application-level rate limit (e.g.
  `slowapi`). Enabling one is on the roadmap and would mean every
  consumer is throttled even before reaching the database.

### Elevation of privilege

- **Threat.** A successful intrusion of one container leads to
  compromise of others or of the host.
- **Mitigation.**
  - Each service runs in a separate container with its own
    dependency footprint. The dashboard and API share an image
    because they share the `api_service` package, but their commands
    differ.
  - PostgreSQL is bound to the host loopback, not accessible from the
    public network.
  - Docker Compose's `depends_on: condition: service_healthy` chains
    enforce a deterministic startup order so a failing component
    cannot be silently bypassed.
- **Open issue.** Containers currently run as root inside the
  filesystem. Adding a dedicated unprivileged user in each
  Dockerfile is straightforward and on the roadmap.

## Dependencies and supply chain

- All Python dependencies are pinned to exact versions in the
  per-service `requirements.txt` files. Renovate or Dependabot
  surveillance is recommended at the repository level but not yet
  enabled in this repository.
- The base images are pinned to a specific minor (`python:3.11-slim`,
  `postgres:15-alpine`) but not to a digest; pinning to digests is
  the next step for fully reproducible builds.
- No automatic image scanning runs today. Adding Trivy in CI is on
  the roadmap.

## What this project does **not** do

- It does not store, infer, or expose any personal data.
- It does not interact with operational law-enforcement systems
  (Eurodac, SIS, VIS, EES, ETIAS, ECRIS-TCN). It is a forecasting
  tool over publicly-released aggregate statistics.
- It does not make decisions; its output is a numerical indicator
  intended for human analysts.

## Versioning of this document

Material changes to the threat model are recorded in commit messages
and reflected in the relevant ADR. The current revision corresponds
to the state of the code on the `main` branch.
