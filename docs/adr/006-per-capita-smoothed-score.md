# ADR-006 — Per-capita, smoothed risk score

- **Status:** Accepted
- **Date:** 2026-11-16

## Context

The risk score was defined as the monthly volume of first-time
applications, log-scaled against the all-time EU peak, multiplied by
`1 + variation`, where `variation` was the change from the previous
month.

Measured over the full history (2008 to 2026, 27 Member States), that
definition behaved poorly:

- the score moved by **22 points a month on average** on a 0-100 scale,
  and by more than 40 points for several small Member States;
- a country's position in the ranking shifted by **6.6 places** from
  one month to the next.

Two things drove this. A month-over-month ratio is mostly noise when a
country registers a few dozen applications, and the most recent months
are routinely revised upwards, which shows up as a sharp fall followed
by a recovery. The level term had its own problem: raw volume ranks
Member States by size, while the project describes its output as the
pressure on a Member State's asylum procedure.

The same measurement exposed a weakness in the forecast. On the old
score the Random Forest beat a naive "same as last month" forecast,
but only because the target was so erratic that anything smoother than
the last value did well: a plain three-month average came within two
points of it.

## Decision

The score is computed in three steps:

1. first-time applications are averaged over **three months** and
   expressed **per 100,000 inhabitants** (Eurostat `tps00001`
   population);
2. the rate is **log-scaled against the highest rate ever observed**
   in any Member State;
3. the result is **adjusted by at most 25 %** for the three-month
   trend: the smoothed volume against the one three months earlier,
   clipped to +/- 50 % and weighted by one half.

The forecast target changes with it. The forest now predicts the
**change** of the score rather than its level, and every retrain
stores the naive baseline's error next to its own.

## Consequences

- Measured on the same history, the score moves by **3.8 points a
  month** and rankings shift by **1.3 places**. A reader can follow a
  country from one month to the next.
- The ranking changes meaning: large Member States with moderate
  per-capita inflows move down, small ones under strain move up. This
  is the intended reading of "pressure", but anyone who used the score
  as a proxy for volume must be told.
- The score reacts more slowly: a sudden surge takes up to three
  months to be fully reflected in the level, and the trend term is
  what signals it in the meantime.
- The forecast gains little over the naive baseline (about 5 % lower
  error, better in 14 of 27 Member States at the time of the change).
  This is stated in the Model Card rather than hidden: on a smooth
  indicator, most of next month's value is this month's value.
- One population reference year is applied to the whole history. This
  is an approximation, documented in the Data Card.
- All cached models are invalidated once: the score version is part of
  the model cache signature.

## Alternatives considered

- **Per-capita level only, no trend term.** The most stable option
  (1.7 points a month, 0.65 places), but blind to acceleration, which
  is half of what the indicator is meant to convey.
- **Year-over-year trend instead of three months.** Handles
  seasonality and is slightly more stable (2.8 points, 1.0 place), but
  reacts a year late to a change of regime.
- **Percentile rank against the historical distribution.** Easy to
  explain ("higher than 90 % of country-months since 2008") but it
  compresses the top of the scale, where the differences matter most.
- **Keeping raw volume and only smoothing it.** Fixes the noise, not
  the fact that the ranking would remain a ranking by country size.
