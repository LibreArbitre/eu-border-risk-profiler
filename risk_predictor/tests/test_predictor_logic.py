from functools import partial

import numpy as np
import pandas as pd
import pytest

import risk_predictor.risk_predictor as rp
from risk_predictor.risk_predictor import (
    calculate_risk_and_predict,
    evaluate_model_holdout,
    get_or_train_model,
    predict_with_quantiles,
    temporal_split,
)


class MockEngine:
    """Mock SQLAlchemy Engine for testing"""

    def connect(self):
        return self

    def begin(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        pass

    def execute(self, statement, params=None):
        return MockResult()


class MockResult:
    def scalar(self):
        return 1  # Mock model_id

    def fetchone(self):
        return None  # Mock no existing model


class DummyModel:
    def __init__(self, value=1.0):
        self.value = value

    def predict(self, features):  # noqa: ARG002 - signature aligned with sklearn
        return [self.value for _ in range(len(features))]


def _monthly(geo, values, start="2023-01-01"):
    dates = pd.date_range(start=start, periods=len(values), freq="MS")
    return [{"date": d, "geo_code": geo, "total_applications": v} for d, v in zip(dates, values)]


def test_rate_frame_smooths_and_scales_by_population():
    """300 applications a month for 1,000,000 inhabitants = 30 per 100k."""
    group = pd.DataFrame(_monthly("XX", [300] * 8))
    frame = rp.compute_rate_frame(group, population=1_000_000)

    # The first two months cannot be smoothed over three months yet.
    assert frame["rate_per_100k"].iloc[:2].isna().all()
    assert frame["rate_per_100k"].iloc[2:].tolist() == pytest.approx([30.0] * 6)
    assert frame["trend"].tolist() == pytest.approx([0.0] * 8)


def test_rate_frame_trend_is_clipped_both_ways():
    surge = rp.compute_rate_frame(pd.DataFrame(_monthly("XX", [100] * 6 + [1000] * 6)), 1_000_000)
    collapse = rp.compute_rate_frame(pd.DataFrame(_monthly("XX", [1000] * 6 + [10] * 6)), 1_000_000)

    assert surge["trend"].max() == pytest.approx(rp.TREND_CLIP)
    assert collapse["trend"].min() == pytest.approx(-rp.TREND_CLIP)


def test_rate_frame_counts_a_rise_from_zero_as_the_maximum_rise():
    frame = rp.compute_rate_frame(pd.DataFrame(_monthly("XX", [0] * 6 + [50] * 6)), 1_000_000)
    assert frame["trend"].max() == pytest.approx(rp.TREND_CLIP)
    assert frame["trend"].min() >= 0


def test_rate_frame_keeps_unpublished_months_as_gaps():
    """A missing month is not a zero: it leaves a hole in the smoothed rate."""
    rows = _monthly("XX", [300] * 10)
    del rows[5]  # this month was never published
    frame = rp.compute_rate_frame(pd.DataFrame(rows), 1_000_000)

    assert len(frame) == 10  # the calendar is complete again
    assert np.isnan(frame["total_applications"].iloc[5])
    assert frame["rate_per_100k"].iloc[5:8].isna().all()  # windows touching the hole
    assert frame["rate_per_100k"].iloc[8] == pytest.approx(30.0)


def test_rate_frame_drops_a_trailing_zero_after_a_substantial_month():
    frame = rp.compute_rate_frame(pd.DataFrame(_monthly("XX", [500] * 8 + [0])), 1_000_000)
    assert len(frame) == 8
    assert frame["total_applications"].iloc[-1] == 500


def test_score_is_relative_to_population():
    """Same applications, ten times fewer inhabitants: higher pressure."""
    df = pd.DataFrame(_monthly("BIG", [1000] * 15) + _monthly("SMALL", [1000] * 15))
    frames, reference_log = rp.build_score_frames(df, population={"BIG": 10_000_000, "SMALL": 1_000_000})

    big = frames["BIG"]["risk_score"].iloc[-1]
    small = frames["SMALL"]["risk_score"].iloc[-1]
    assert small > big > 0
    # The highest rate ever observed defines the top of the scale.
    assert small == pytest.approx(100.0)
    assert reference_log == pytest.approx(np.log1p(100.0))


def test_countries_without_population_are_skipped():
    df = pd.DataFrame(_monthly("FR", [1000] * 15) + _monthly("ZZ", [1000] * 15))
    frames, _ = rp.build_score_frames(df)
    assert list(frames) == ["FR"]


def test_risk_calculation_nominal():
    """Two Member States of similar size: stable and low vs high and rising."""
    # PT: 100 applications every month. BE: starts at 1000, +100 a month.
    data = _monthly("PT", [100] * 30) + _monthly("BE", [1000 + i * 100 for i in range(30)])
    results = calculate_risk_and_predict(pd.DataFrame(data), MockEngine())

    assert not results.empty
    stable = results[results["geo_code"] == "PT"].iloc[0]
    rising = results[results["geo_code"] == "BE"].iloc[0]

    assert stable["risk_score_calculated"] > 0
    assert rising["risk_score_calculated"] > stable["risk_score_calculated"]
    assert stable["trend_3m"] == pytest.approx(0.0)
    assert rising["trend_3m"] > 0
    # 100 a month for 11,424,031 inhabitants.
    assert stable["applications_per_100k"] == pytest.approx(100 / 11_424_031 * 100_000)
    # Three horizons per country, all within the scale.
    assert len(results) == 6
    assert results["predicted_risk_score"].between(0, 100).all()


def test_zero_division_protection():
    """A country that never receives an application scores 0, without errors."""
    results = calculate_risk_and_predict(pd.DataFrame(_monthly("PT", [0] * 30)), MockEngine())

    assert not results.empty
    assert (results["risk_score_calculated"] == 0).all()
    assert results["predicted_risk_score"].between(0, 100).all()


def test_reuse_model_when_data_signature_matches(monkeypatch):
    df = pd.DataFrame(_monthly("FR", [5000 + i * 10 for i in range(30)]))

    reused_model = DummyModel(value=2.0)  # the model predicts a CHANGE of +2 points
    reuse_signature = "stable-hash"
    was_trained = {"called": False}

    def fake_loader(engine, geo_code):  # noqa: ARG001 - engine unused in mock
        return reused_model, 99, pd.Timestamp.utcnow().to_pydatetime().replace(tzinfo=None), {
            "data_signature": reuse_signature
        }

    def fake_persister(engine, geo_code, model, metadata):  # noqa: ARG001 - engine unused in mock
        pytest.fail("Persist should not be called when reusing model")

    def fake_train(train_df):  # noqa: ARG001 - train_df unused in mock
        was_trained["called"] = True
        return DummyModel(value=0.0)

    monkeypatch.setattr(rp, "load_latest_model", fake_loader)
    monkeypatch.setattr(rp, "persist_model", fake_persister)
    monkeypatch.setattr(rp, "compute_data_signature", lambda df, context=None: reuse_signature)
    monkeypatch.setattr(rp, "train_model", fake_train)
    monkeypatch.setattr(
        rp,
        "get_or_train_model",
        partial(get_or_train_model, loader=fake_loader, persister=fake_persister),
    )

    engine = MockEngine()

    results = calculate_risk_and_predict(df, engine)

    assert not was_trained["called"], "Training should be skipped when data signature matches"
    assert not results.empty
    # Each horizon adds the predicted change to the previous step.
    current = results["risk_score_calculated"].iloc[0]
    expected = [min(100.0, current + 2.0 * step) for step in (1, 2, 3)]
    assert results["predicted_risk_score"].tolist() == pytest.approx(expected)

    # Direct call still reports reuse
    model, model_id, info = rp.get_or_train_model(engine, "FR", df)

    assert model is reused_model
    assert model_id == 99
    assert info["reused"] is True


def test_signature_includes_global_context():
    """The cache signature must change when the global normalisation shifts,
    even if the country's own series is identical."""
    df = pd.DataFrame(
        {
            "date": pd.date_range("2023-01-01", periods=6, freq="MS"),
            "total_applications": [10, 20, 30, 40, 50, 60],
        }
    )

    base = rp.compute_data_signature(df)
    ctx_a = rp.compute_data_signature(df, context="global_max_log=10.000000000000")
    ctx_b = rp.compute_data_signature(df, context="global_max_log=11.000000000000")

    assert base != ctx_a
    assert ctx_a != ctx_b
    # Deterministic for identical inputs.
    assert ctx_a == rp.compute_data_signature(df, context="global_max_log=10.000000000000")


def test_temporal_split_holds_out_recent_rows():
    df = pd.DataFrame({
        "date": pd.date_range("2023-01-01", periods=20, freq="MS"),
        "risk_score": range(20),
        "lag_1": range(20),
        "lag_2": range(20),
        "lag_3": range(20),
        "month": [d.month for d in pd.date_range("2023-01-01", periods=20, freq="MS")],
    })

    train_part, test_part = temporal_split(df, test_ratio=0.2, min_test=2, min_train=6)

    assert test_part is not None
    assert len(test_part) == 4  # round(20 * 0.2) = 4
    assert len(train_part) == 16
    # Test set must be the most recent slice
    assert test_part["date"].min() > train_part["date"].max()


def test_temporal_split_returns_none_test_when_too_short():
    df = pd.DataFrame({
        "date": pd.date_range("2023-01-01", periods=5, freq="MS"),
        "risk_score": range(5),
    })

    train_part, test_part = temporal_split(df, test_ratio=0.2, min_test=2, min_train=6)

    assert test_part is None
    assert len(train_part) == 5


def test_evaluate_model_holdout_handles_empty_inputs():
    model = DummyModel(value=5.0)
    assert evaluate_model_holdout(None, model) is None
    assert evaluate_model_holdout(pd.DataFrame(), model) is None


def test_evaluate_model_holdout_returns_mae():
    test_df = pd.DataFrame({
        "lag_1": [1, 2, 3],
        "delta_1": [1, 2, 3],
        "month": [1, 2, 3],
        "delta": [4.0, 6.0, 8.0],
    })
    model = DummyModel(value=5.0)
    # Predictions are constant 5; absolute errors are |4-5|, |6-5|, |8-5| = 1, 1, 3 -> mean = 5/3
    assert evaluate_model_holdout(test_df, model) == pytest.approx(5 / 3)


def test_naive_holdout_mae_is_the_mean_absolute_change():
    """Predicting "same as last month" is wrong by exactly the change."""
    test_df = pd.DataFrame({"delta": [1.0, -3.0, 2.0]})
    assert rp.naive_holdout_mae(test_df) == pytest.approx(2.0)
    assert rp.naive_holdout_mae(None) is None
    assert rp.naive_holdout_mae(pd.DataFrame()) is None


def test_is_data_fresh_rejects_empty_frame():
    assert rp._is_data_fresh(pd.DataFrame()) is False
    assert rp._is_data_fresh(None) is False


def test_is_data_fresh_rejects_old_data(monkeypatch):
    monkeypatch.setattr(rp, "DATA_FRESHNESS_MAX_AGE_DAYS", 90)
    old_date = (pd.Timestamp.utcnow().tz_localize(None) - pd.Timedelta(days=200)).normalize()
    df = pd.DataFrame({"date": [old_date], "geo_code": ["FR"], "total_applications": [1000]})
    assert rp._is_data_fresh(df) is False


def test_is_data_fresh_accepts_recent_data(monkeypatch):
    monkeypatch.setattr(rp, "DATA_FRESHNESS_MAX_AGE_DAYS", 90)
    recent_date = (pd.Timestamp.utcnow().tz_localize(None) - pd.Timedelta(days=30)).normalize()
    df = pd.DataFrame({"date": [recent_date], "geo_code": ["FR"], "total_applications": [1000]})
    assert rp._is_data_fresh(df) is True


class _ForestStub:
    """Minimal stand-in for sklearn's RandomForestRegressor used by the
    quantile extraction tests. Each estimator has a fixed predict() output."""

    def __init__(self, per_tree_values):
        self.estimators_ = [_TreeStub(v) for v in per_tree_values]

    def predict(self, features):
        # sklearn behaviour: average across trees.
        return np.array([np.mean([e.predict(features)[0] for e in self.estimators_])])


class _TreeStub:
    def __init__(self, value):
        self._value = float(value)

    def predict(self, features):  # noqa: ARG002 — features unused
        return np.array([self._value])


def test_predict_with_quantiles_returns_mean_and_quantiles():
    forest = _ForestStub([10.0, 20.0, 30.0, 40.0, 50.0])
    point, p10, p90 = predict_with_quantiles(forest, np.zeros((1, 4)))
    assert point == pytest.approx(30.0)
    assert p10 == pytest.approx(np.quantile([10, 20, 30, 40, 50], 0.1))
    assert p90 == pytest.approx(np.quantile([10, 20, 30, 40, 50], 0.9))


def test_predict_with_quantiles_handles_missing_estimators():
    class _NoEstimators:
        def predict(self, features):  # noqa: ARG002
            return np.array([42.0])

    point, p10, p90 = predict_with_quantiles(_NoEstimators(), np.zeros((1, 4)))
    assert point == pytest.approx(42.0)
    assert p10 is None
    assert p90 is None


def test_predict_with_quantiles_handles_none_model():
    point, p10, p90 = predict_with_quantiles(None, np.zeros((1, 4)))
    assert (point, p10, p90) == (None, None, None)


def test_ensure_predictions_schema_swallows_engine_errors(monkeypatch):
    """The migration helper must never crash the predictor — if the DB
    rejects the ALTER (insufficient privilege, missing table…), we log
    and continue so the next INSERT raises the original informative
    error rather than masking it with a startup crash."""

    class _BadEngine:
        def begin(self):  # pragma: no cover — exercised through the call below
            raise RuntimeError("simulated DB outage")

    # Should not raise.
    rp.ensure_predictions_schema(engine=_BadEngine())
