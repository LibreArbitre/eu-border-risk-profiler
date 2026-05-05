# Model Card — EU Border Risk Profiler

This document describes the predictive component of the EU Border Risk
Profiler in the spirit of the Model Cards proposed by Mitchell et al.
(2019) and required for high-risk AI systems under Regulation (EU)
2024/1689 (the AI Act). It is intended to be read alongside the
[Data Card](DATA_CARD.md), which describes the underlying Eurostat
dataset.

## Model details

- **Family:** scikit-learn `RandomForestRegressor`, one independent
  estimator per EU Member State (27 models).
- **Hyperparameters:** `n_estimators=50`, `random_state=42`. No
  per-country tuning. Hyperparameters and the exact pickled artifact
  for every fit are stored in PostgreSQL (`model_registry` table)
  alongside a SHA-256 signature of the training frame.
- **Inputs (features):** four scalar features per observation —
  `lag_1`, `lag_2`, `lag_3` (the country's calculated risk score for
  the three preceding months) and `month` (1-12 calendar month
  index).
- **Output (target):** the calculated risk score (0-100) for the
  prediction target month. The score is a deterministic transform of
  the underlying volume — `vol_norm × (1 + variation) × 100` — defined
  in [`risk_predictor.calculate_risk_and_predict`](../risk_predictor/risk_predictor.py).
- **Prediction horizon:** three steps ahead (M+1, M+2, M+3). M+2 and
  M+3 are produced autoregressively, feeding earlier predictions back
  in as lag features.
- **Refit cadence:** triggered when the SHA-256 signature of a country's
  training frame changes (i.e. Eurostat published new or revised
  values), or when the persisted model is older than
  `MODEL_MAX_AGE_DAYS` (default 30). Otherwise the cached model is
  reused.
- **Evaluation:** the most recent ~20 % of observations are held out
  chronologically; a candidate model is fit on the older portion and
  scored on the hold-out (`test_mae`). The deployed model is then
  refit on the full series. See [ADR-003](adr/003-temporal-train-test-split.md).

## Intended use

The system is designed for **operational situational awareness** by
migration policy analysts working at, or with, EU institutions. It
helps surface countries where short-term administrative pressure is
likely to rise so resources, dialogue, or contingency plans can be
prepared.

The output of the model — a 0-100 score — represents an **expected
administrative load** on a Member State's first-time asylum procedure
in a given month, _conditional on the historical dynamics of that
single Member State_. It is a comparative indicator across time, not
a forecast of any individual outcome.

## Out-of-scope use

This model **must not** be used for, or to inform:

- decisions concerning individual asylum applicants, including
  acceptance, rejection, prioritisation, or routing;
- automated allocation of asylum seekers between Member States;
- border control decisions, refusal of entry, or any individual
  policing action;
- public communication that frames the score as an expected number of
  arrivals or as a moral judgement on the populations involved.

The score reflects the **administrative pressure on a Member State's
first-time-applicant procedure**, not a judgement on the people
applying. Press, policy, and operational consumers should be briefed
on this distinction before being granted access.

## Performance

We report the Mean Absolute Error of the candidate model on the
chronological 20 % hold-out, per country, refreshed at every
significant retrain. Typical values today are between 5 and 15 risk
points for the larger Member States and noisier (10-30) for the
smaller series. Drift relative to the previously deployed model is
flagged when MAE worsens by more than `DRIFT_TOLERANCE` (default
15 %) and is logged as a warning; the deployment is not rolled back
automatically.

The system does not currently report prediction intervals. Adding
them is on the roadmap (quantile forests or conformal prediction).
Until then, point estimates should be read with the corresponding
country-level test MAE in mind.

## Known limitations

- **Cascading error on M+2 and M+3.** The autoregressive feed-back of
  predicted scores as lag features compounds error at longer horizons.
  The dashboard shows the average of M+1 to M+3 in the headline
  heatmap, which softens but does not fix the issue.
- **Country-only granularity.** All citizenships are aggregated to
  `TOTAL` in the harvest pipeline. The model cannot distinguish
  pressure originating from different source populations.
- **Surprise to structural breaks.** Historical training cannot
  anticipate events whose dynamics are unprecedented in the training
  window — the model would have under-predicted the 2015 Syrian arrival
  surge or the early 2022 Ukrainian displacement, and similar future
  events will surprise it. The risk-score formula partially compensates
  via the volume normalisation against the all-time EU peak, but the
  forecast itself remains inertial.
- **Reporting lag in the source.** Eurostat publishes monthly with a
  one- to two-month lag and revises older months; the most recent
  reported month often shows a structural undercount. The harvester
  drops a country's last month if it is exactly zero while the prior
  month was substantial, but this heuristic is conservative and
  misses subtler undercounts.
- **Honest evaluation scope.** Hold-out MAE measures one-step-ahead
  performance on the calculated risk score. It does not measure the
  practical utility of the score for an analyst, nor the statistical
  calibration of the M+2 / M+3 horizons.

## Ethical considerations

- The training data contains **no personal data** within the meaning of
  Regulation (EU) 2016/679 (GDPR). It is fully aggregated by Eurostat
  to the (date, destination country, citizenship, applicant type)
  level and re-aggregated by this project to (date, destination
  country) before any model fits.
- Outputs reflect administrative dynamics, not the moral character or
  individual circumstances of asylum seekers. Communication around the
  scores must preserve this distinction.
- The model is a deterministic transform plus a Random Forest — its
  outputs are reproducible from the inputs and can be inspected. Pickle
  artifacts are stored alongside their hyperparameters and training
  signature so any historical decision can be traced to the exact
  artifact and data state that produced it.

## Maintenance and governance

- **Owner:** the maintainer of this repository.
- **Retrain trigger:** automatic on data signature change or model age.
- **Rollback:** removing the offending row from `model_registry` causes
  the next run to retrain from the latest data; older artifacts in
  the same table can be promoted by manipulating `trained_at`.
- **Change log:** model behaviour changes are described in commit
  messages and in the relevant ADR (see `docs/adr/`).
