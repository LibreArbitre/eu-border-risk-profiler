# Architecture Decision Records

This directory captures the load-bearing architectural choices made on the
EU Border Risk Profiler. Each record follows Michael Nygard's lightweight
ADR template — _Context / Decision / Consequences / Alternatives_ — and is
immutable once accepted. Subsequent decisions that supersede an earlier
record link back to it explicitly.

| ID | Title | Status |
|----|-------|--------|
| [ADR-001](001-postgresql-as-shared-store.md) | PostgreSQL as the shared persistence layer | Accepted |
| [ADR-002](002-staging-table-for-atomic-harvest.md) | Staging table for atomic Eurostat harvest | Accepted |
| [ADR-003](003-temporal-train-test-split.md) | Temporal train/test split for honest evaluation | Accepted |
| [ADR-004](004-optional-api-key-auth.md) | Optional `X-API-Key` authentication | Accepted |
| [ADR-005](005-streamlit-for-analyst-dashboard.md) | Streamlit for the analyst dashboard | Accepted |

## Conventions

- File names use the form `NNN-kebab-case-title.md`.
- Records are written in English to match Eurostat and EU agency
  documentation practice.
- The status of a record stays "Accepted" unless explicitly "Superseded by
  ADR-NNN" — there is no "Proposed" state in this repository because we
  document decisions after they ship, not before.
