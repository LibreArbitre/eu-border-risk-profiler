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
- **Hyperparameters:** `n_estimators=50`, `min_samples_leaf=5`,
  `random_state=42`. No per-country tuning. Hyperparameters and the
  exact pickled artifact for every fit are stored in PostgreSQL
  (`model_registry` table) alongside a SHA-256 signature of the
  training frame.
- **The score being forecast:** a deterministic 0-100 indicator
  computed in [`risk_predictor`](../risk_predictor/risk_predictor.py)
  (`compute_rate_frame`, `add_score`):
  1. first-time applications are averaged over three months and
     expressed per 100,000 inhabitants;
  2. that rate is log-scaled against the highest rate ever observed
     in any Member State, so one exceptional episode does not flatten
     every other value;
  3. the result is adjusted by at most 25 % for the three-month trend
     (smoothed volume against the one three months earlier, clipped to
     +/- 50 %).

  See [ADR-006](adr/006-per-capita-smoothed-score.md) for why this
  replaced the earlier volume times month-over-month formula.
- **Inputs (features):** three scalar features per observation:
  `lag_1` (the score of the previous month), `delta_1` (its last
  month-over-month change) and `month` (1-12 calendar month index).
- **Output (target):** the **change** of the score from one month to
  the next. The forecast is the previous value plus the predicted
  change. The score is highly persistent, and a forest trained on its
  level cannot extrapolate and loses to assuming no change.
- **Prediction horizon:** three steps ahead (M+1, M+2, M+3), from the
  last month each Member State has published. M+2 and M+3 are produced
  autoregressively, each step starting from the previous forecast.
- **Uncertainty band:** the 10th and 90th percentiles of the per-tree
  predictions are stored and served as P10 / P90 next to the point
  estimate.
- **Refit cadence:** triggered when the SHA-256 signature of a country's
  training frame changes (Eurostat published new or revised values,
  the EU-wide reference rate moved, or the score definition changed),
  or when the persisted model is older than `MODEL_MAX_AGE_DAYS`
  (default 30). Otherwise the cached model is reused.
- **Evaluation:** the most recent ~20 % of observations are held out
  chronologically; a candidate model is fit on the older portion and
  scored on the hold-out (`test_mae`), next to the error of the naive
  "same as last month" forecast on the same months (`naive_test_mae`).
  The deployed model is then refit on the full series. See
  [ADR-003](adr/003-temporal-train-test-split.md).

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
chronological 20 % hold-out (about 41 months per country), refreshed
at every retrain, always next to the naive baseline that predicts no
change. Both are stored in `model_registry.hyperparameters` and logged.

Figures from the retrain of 16 November 2026, one-step-ahead, in score
points on the 0-100 scale, averaged over the 27 Member States:

| Forecast | Hold-out MAE |
|----------|--------------|
| Random Forest on the change of the score | 3.39 |
| Naive: same as last month | 3.58 |

The model is about 5 % better than the naive forecast on average and
beats it in 14 of the 27 Member States. **This is a small edge, and it
should be read as such:** the score is smooth by construction, so most
of what can be said about next month is already in this month's value.
The forecast is a mild refinement of the current score, not an early
warning system.

Drift relative to the previously deployed model is flagged when MAE
worsens by more than `DRIFT_TOLERANCE` (default 15 %) and is logged as
a warning; the deployment is not rolled back automatically.

The P10 / P90 band comes from the spread of the individual trees. It
describes the model's own disagreement, not a calibrated confidence
interval, and at M+2 and M+3 it does not accumulate the uncertainty of
the earlier steps.

## Known limitations

- **Cascading error on M+2 and M+3.** The autoregressive feed-back of
  predicted scores as lag features compounds error at longer horizons.
  The dashboard's tiles, heatmap and ranking show the score of the
  last published month; the forecast only appears in the country
  card, as the average of M+1 to M+3 with its band.
- **Country-only granularity.** The harvest keeps the per-citizenship
  breakdown for the dashboard, but the score and the model only use
  each Member State's total. The model cannot distinguish pressure
  originating from different source populations.
- **One population reference year.** The per-capita rate uses the
  resident population on 1 January 2026 (Eurostat `tps00001`) for the
  whole history. Population changes slowly, but rates before roughly
  2015 are a few percent off for the Member States whose population
  moved the most.
- **A trend exposed to late reporting.** Recent months are often
  revised upwards. Averaging over three months dampens this, but a
  provisional low month still pulls the trend down until it is
  revised.
- **Surprise to structural breaks.** Historical training cannot
  anticipate events whose dynamics are unprecedented in the training
  window — the model would have under-predicted the 2015 Syrian arrival
  surge or the early 2022 Ukrainian displacement, and similar future
  events will surprise it. The forecast is inertial by design.
- **Reporting lag in the source.** Eurostat publishes monthly with a
  one- to two-month lag and revises older months; the most recent
  reported month often shows a structural undercount. A month that
  is not published yet is left out entirely (never counted as zero),
  so Member States are assessed on different latest months; the
  predictor also drops a last month that is exactly zero while the
  prior month was substantial. Subtler undercounts are not corrected.
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
