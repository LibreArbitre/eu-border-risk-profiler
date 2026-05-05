# ADR-002 — Staging table for atomic Eurostat harvest

- **Status:** Accepted
- **Date:** 2026-04-12

## Context

The harvester pulls a full bulk download of the Eurostat dataset
`migr_asyappctzm` (~440 MB TSV) and replaces the contents of
`asylum_data` end-to-end. The original implementation truncated the
production table immediately, then streamed parsed chunks back in.

That sequence has two failure modes:

1. **Mid-flight failure.** A network blip, a parser exception or an
   out-of-memory kill between `TRUNCATE` and the final chunk leaves the
   production table partially populated until the next 24 h cycle. The
   API and dashboard return inconsistent results in the meantime.
2. **Visible empty window.** Even on a successful run, downstream
   readers (and the predictor's polling loop) observe an empty table
   for the duration of the parse — typically 60 to 90 seconds — which
   wastes wait cycles and can make a freshly started predictor train on
   no data.

## Decision

Apply a staging-table swap pattern:

1. `DROP TABLE IF EXISTS asylum_data_staging` then re-create it with the
   same shape and unique index as `asylum_data`.
2. Stream every parsed chunk into the staging table using the existing
   `INSERT ... ON CONFLICT DO UPDATE` summing semantics. The production
   table is not touched.
3. Once all chunks are processed, run a single transaction that
   `TRUNCATE`s `asylum_data`, `INSERT ... SELECT`s every staging row
   into it, and `DROP`s the staging table. The transaction commits as
   one atomic unit.

If any step before the final transaction fails, `asylum_data` retains
the prior successful snapshot. PostgreSQL's transactional `TRUNCATE`
guarantees concurrent readers see either the old state or the new
state, never a partial swap.

The harvester's `harvester_meta.eurostat_last_modified` row is updated
**after** the swap commits, so the next run re-downloads on the next
attempt if the swap was interrupted.

## Consequences

- **Positive.** The production table is never empty for a non-trivial
  window. A failed harvest is a no-op for downstream services. Readers
  always see a consistent view.
- **Negative.** Brief 2× storage during the swap (~80 MB at the
  current aggregation level). Acceptable until nationality breakdown
  is added, at which point the staging table grows proportionally.
- **Operational.** The swap holds an `ACCESS EXCLUSIVE` lock on
  `asylum_data` for the duration of the `INSERT ... SELECT` (~1
  second on the current data volume). API queries that arrive during
  that window block briefly. Acceptable given the low query rate.

## Alternatives considered

- **DELETE + INSERT in one transaction** without a staging table —
  works for small datasets but holds row-level locks and bloats the
  table for autovacuum to clean later. Rejected on operational grounds.
- **Blue/green table swap via `ALTER TABLE ... RENAME`** — atomic and
  zero-downtime in theory, but breaks every prepared query, view or
  foreign key that references the table by name. Out of scope today,
  reasonable to revisit if read load grows.
- **CDC / replication slot on a separate ingestion DB** — overkill for
  a monthly publication cadence. Deferred.
