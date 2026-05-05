# ADR-001 — PostgreSQL as the shared persistence layer

- **Status:** Accepted
- **Date:** 2025-12-04

## Context

The system runs four cooperating services that need to exchange state:

- the **harvester** writes raw Eurostat asylum data and remembers the
  remote `Last-Modified` header to avoid redundant downloads;
- the **predictor** reads aggregated history, persists trained models as
  binary artifacts, and writes its predictions;
- the **API** reads predictions and history;
- the **dashboard** consumes the API.

State sharing happens across container restarts and across host
redeployments, with concurrent reads and the occasional concurrent write
during a daily refresh window. The data is structured (date / geo /
metric tuples) and benefits from referential integrity, indexed lookups,
and transactional writes. Volumes are small at country aggregation
(< 100 MB total today) but expected to grow if nationality breakdown is
added.

## Decision

Use a single PostgreSQL 15 instance as the shared persistence layer for
all four services. Connection details flow through environment variables;
the database lives in a named Docker volume (`db_data`) so it survives
container recreation.

The schema lives in [`db_init/db_schema.sql`](../../db_init/db_schema.sql)
and is bootstrapped via the standard
`/docker-entrypoint-initdb.d` mechanism on first start.

## Consequences

- **Positive.** A single source of truth; no service-to-service RPCs for
  state; `LISTEN/NOTIFY`, materialised views, and stored procedures are
  available if needed; mature backup tooling (`pg_dump`, WAL archiving);
  PostgreSQL is the standard relational database in EU agency
  deployments, including eu-LISA's own modern stack.
- **Negative.** Single point of failure for the stack; downtime of the
  database means downtime of every service. Mitigated locally by Docker
  health checks and `restart: always`; in production this would warrant
  a managed instance with replication.
- **Operational.** A schema migration tool (Alembic) is not yet in place;
  changes are made by editing `db_schema.sql` and rebuilding, which is
  acceptable for a project of this maturity but should be revisited
  before introducing breaking schema changes.

## Alternatives considered

- **SQLite** — sufficient for single-process tools but does not fit our
  multi-container topology (file-locking semantics on a shared volume
  are error-prone). Rejected.
- **Per-service stores** (e.g. SQLite for harvester metadata, a key-value
  store for models, a separate read store for the API) — would increase
  surface area without obvious benefit at our scale. Rejected.
- **Object storage (S3) for model artifacts** with PostgreSQL only for
  metadata — defensible at scale but introduces a second dependency for
  marginal gain when the registry is < 100 KB per model. Deferred.
