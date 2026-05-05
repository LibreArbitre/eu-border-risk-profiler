# ADR-004 — Optional `X-API-Key` authentication

- **Status:** Accepted
- **Date:** 2026-04-22

## Context

The API exposes three endpoints that read from PostgreSQL:
`/api/v1/risk/predict`, `/api/v1/risk/current` (with `/latest` alias),
and `/api/v1/data/history/{geo_code}`. The data is itself public — it
originates from Eurostat — but a publicly-reachable deployment with no
access control invites scraping, throttle exhaustion, and accidental
exposure if the URL is ever shared in a context the operator did not
intend. eu-LISA infrastructure typically wraps every public surface in
some form of identification, even when the underlying data is open, to
keep an audit trail of consumers.

We needed an authentication mechanism that:

1. is **opt-in** so single-host docker-compose setups remain reachable
   without configuration;
2. costs nothing to operate when disabled (no key store, no token
   refresh, no identity provider dependency);
3. is trivial to integrate into the bundled Streamlit dashboard so
   the end-to-end demo stays one-click;
4. can be replaced later by a stronger mechanism without breaking the
   wire format clients already use.

## Decision

Implement a single static header-based scheme:

- The API reads `API_KEY` from its environment at startup. When unset
  or empty, every endpoint stays open — the legacy behaviour.
- When set, every protected endpoint requires the same value in the
  `X-API-Key` request header. A `Depends(require_api_key)` dependency
  is wired into each `@app.get(...)` decorator. `/health` remains
  public so docker health checks and external monitoring keep
  working.
- The Streamlit dashboard reads the same `API_KEY` env var and
  forwards the header on every outbound request. No interactive login
  flow.

The shared key lives in the environment, never in the database. It
rotates by editing the env var and restarting the API + dashboard
containers; rotation is fast because there is only one secret.

## Consequences

- **Positive.** Public deployments can be locked down with a single
  env var and a container restart. The API and dashboard wire format
  stays unchanged. No new infrastructure dependency.
- **Negative.** A single shared secret means every consumer
  authenticates as "the same caller". There is no per-user audit
  trail and no per-consumer revocation. Acceptable while the consumer
  set is "the bundled dashboard" and "the operator's curl"; not
  acceptable for multi-tenant exposure.
- **Operational.** The key is present in process memory and in the
  container's environment. Logging frameworks must not echo headers.
  The current logging configuration only emits structured fields
  explicitly, so this is not a concern today.

## Alternatives considered

- **OAuth 2.0 / OIDC** with a Keycloak or eu-LISA-internal IdP —
  appropriate at agency scale, overkill for a single-tenant analyst
  tool. Reasonable next step if the project graduates to multi-user.
- **JWT with HMAC** — solves rotation and per-consumer revocation but
  introduces clock-skew handling and a token issuer. Overkill at this
  stage.
- **Mutual TLS** — strongest option for service-to-service traffic but
  shifts the operational burden to certificate distribution. Out of
  scope until we have multiple machine consumers.

## Migration path

If we need multi-tenant access we will:

1. Introduce a `consumers` table (consumer name, hashed key, scopes)
   keyed by the `X-API-Key` value.
2. Keep the same wire format; only the validation logic changes.
3. Add an audit table that records `(consumer_id, endpoint,
   timestamp)` per call, satisfying the agency expectation of access
   traceability.

That migration would supersede this ADR.
