# ADR-003 — Temporal train/test split for honest evaluation

- **Status:** Accepted
- **Date:** 2026-04-18

## Context

The predictor trains one Random Forest regressor per EU country on
roughly 12-200 monthly observations. Earlier iterations of the code
reported a Mean Absolute Error computed on the same rows the model had
just been fit on. That value is the in-sample residual error; it
collapses toward zero as model complexity grows and tells us nothing
about generalization.

The code also compared a previous model's in-sample MAE against the new
model's in-sample MAE for "drift detection". Two residuals on different
datasets are not comparable, so the drift signal was effectively
random.

## Decision

For every training cycle:

1. Sort the country's frame chronologically. Reserve the last
   `HOLDOUT_TEST_RATIO` (default 20 %) of rows as a hold-out test set.
   Skip the hold-out evaluation entirely if the series is too short
   (`HOLDOUT_MIN_TRAIN`, `HOLDOUT_MIN_TEST` thresholds).
2. Fit a candidate model on the train portion only. Record its MAE on
   the unseen hold-out as `test_mae`.
3. If a previously persisted model exists, score it on the same
   hold-out frame to obtain `prev_test_mae`. The drift comparison is
   now apples-to-apples.
4. Refit the deployed model on the full series — the candidate served
   only to measure honest performance, but at inference time we want
   the model to have seen the most recent month.
5. Persist `test_mae`, `test_size`, and `prev_test_mae` alongside the
   model artifact in `model_registry.hyperparameters`.

`evaluate_model` (in-sample) is kept for backwards compatibility but is
labelled as a residual indicator only.

## Consequences

- **Positive.** The reported MAE is now a meaningful generalization
  signal that an analyst can use to weigh predictions per country.
  Drift detection compares like with like and the
  `DRIFT_TOLERANCE` threshold becomes interpretable.
- **Negative.** Two model fits per training cycle instead of one.
  Negligible at our scale (< 5 seconds for 27 countries) but worth
  flagging if model complexity grows.
- **Limitations.** Some short national series (e.g. Cyprus, Malta in
  early years) cannot support a meaningful hold-out and we silently
  fall back to no honest evaluation for those countries. The
  configuration thresholds are tuned for monthly granularity and would
  need revisiting under a different cadence.

## Alternatives considered

- **K-fold cross-validation** — re-shuffles time and leaks the future
  into training. Rejected for time-series data.
- **`TimeSeriesSplit` with rolling-origin** — more robust, gives a
  standard-deviation around the MAE. Reasonable next step but
  heavier; we deferred it until model complexity warrants the spend.
- **Walk-forward backtesting** — gold standard but expensive in
  compute. Out of scope for the current cadence.
