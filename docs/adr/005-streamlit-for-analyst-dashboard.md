# ADR-005 — Streamlit for the analyst dashboard

- **Status:** Accepted
- **Date:** 2025-12-04

## Context

The dashboard is the user-facing surface of the project. Its consumers
are migration analysts who need an at-a-glance heatmap, a country
ranking and a country-level deep-dive — not a configurable BI tool.
The team writing the rest of the stack (harvester, predictor, API) is
Python-centric and shares a single dependency footprint. Iteration
speed matters more than fine-grained UI control.

## Decision

Use Streamlit as the dashboard runtime, served from the same Docker
image as the FastAPI backend (the two share the `api_service/`
package). The dashboard speaks to the API over HTTP only — it has no
direct database connection — so the boundary between "compute /
storage" and "presentation" is clear.

Plotly is the charting library because it integrates cleanly with
Streamlit, supports the choropleth map we need, and produces
interactive output suitable for analysts who want to hover for
context.

## Consequences

- **Positive.** A single-file dashboard (`api_service/dashboard.py`)
  delivers the full analyst experience in roughly 500 lines. The
  Python team owns the entire stack with no JavaScript build pipeline.
  Iteration is essentially editing one file and reloading. Plotly maps
  and progress columns are first-class.
- **Negative.** Streamlit reruns the entire script on every
  interaction, which forces explicit caching (`@st.cache_data`) for
  expensive operations and complicates anything stateful. Concurrency
  is limited: each connected client occupies a Tornado worker, so the
  dashboard does not scale to hundreds of simultaneous users on a
  single container.
- **Limitations.** Custom CSS is supported but not first-class;
  internationalisation is not built in; XSRF and CORS knobs are
  exposed but coarse. Acceptable for a single-tenant analyst tool.

## Alternatives considered

- **React + Vite + a charting lib (Recharts / Visx)** — the strongest
  long-term option, gives full UI control, scales horizontally
  trivially. Rejected at this stage because the build pipeline,
  bundler config and routing add maintenance overhead the team did
  not want to take on for a focused tool.
- **Dash (Plotly)** — closer to a real web framework than Streamlit
  but with a smaller ecosystem and more verbose layout code.
  Rejected on iteration-speed grounds.
- **Apache Superset / Metabase** — full BI suites; powerful, but
  optimised for ad-hoc exploration by non-developer analysts on
  warehouse-scale data. The dashboard we need is opinionated, not
  exploratory. Rejected.
- **Jupyter dashboards / Voilà** — fine for one-off notebook sharing,
  not for a long-lived production surface. Rejected.

## Revisit triggers

This decision should be revisited if any of the following becomes
true:

- More than ~20 simultaneous analysts are expected;
- Mobile / responsive use cases become a primary requirement;
- The dashboard needs to embed authenticated user state per
  consumer rather than a single shared view.
