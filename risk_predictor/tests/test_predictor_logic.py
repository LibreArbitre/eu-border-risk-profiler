from functools import partial

import numpy as np
import pandas as pd
import pytest
import risk_predictor.risk_predictor as rp
from risk_predictor.risk_predictor import (
    calculate_risk_and_predict,
    compute_data_signature,
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


def test_risk_calculation_nominal():
    """
    Test nominal risk calculation:
    - Geo A: Low, Stable
    - Geo B: High, Increasing
    """

    # Create synthetic history
    dates = pd.date_range(start="2023-01-01", periods=15, freq="MS")  # 15 months > 12 requirement

    data = []

    # Geo A: 100 applications every month (Stable)
    for d in dates:
        data.append({"date": d, "geo_code": "GEO_A", "total_applications": 100})

    # Geo B: Starts at 1000, increases by 100 every month (Increasing)
    # Month 0: 1000
    # Month 1: 1100 (+10% increase)
    for i, d in enumerate(dates):
        data.append({"date": d, "geo_code": "GEO_B", "total_applications": 1000 + (i * 100)})

    df = pd.DataFrame(data)
    engine = MockEngine()

    # We execute the function
    # Note: The function will train a model, so it might be slow if we don't mock train_model,
    # but for unit test on 'calculate_risk' logic, we are more interested in the 'calculated_risk_score' output.

    results = calculate_risk_and_predict(df, engine)

    assert not results.empty

    # Check Geo A (Stable)
    # Variation should be 0.
    # Score = Log(100) / GlobalMax * (1 + 0) * 100
    # It should be relatively constant (modulo the global max influence)
    geo_a_results = results[results["geo_code"] == "GEO_A"]
    # We expect some predictions
    assert len(geo_a_results) > 0
    # Last calculated score check
    last_score_a = geo_a_results.iloc[-1]["risk_score_calculated"]
    assert last_score_a > 0

    # Check Geo B (Increasing)
    geo_b_results = results[results["geo_code"] == "GEO_B"]
    last_score_b = geo_b_results.iloc[-1]["risk_score_calculated"]

    # Geo B has higher volume AND positive trend, so Score B should be > Score A
    assert last_score_b > last_score_a

    print(f"Score A (Stable Low): {last_score_a}")
    print(f"Score B (Increasing High): {last_score_b}")


def test_zero_division_protection():
    """Test robustness against 0 volume or missing previous data"""
    dates = pd.date_range(start="2023-01-01", periods=15, freq="MS")
    data = []

    # Geo C: Always 0
    for d in dates:
        data.append({"date": d, "geo_code": "GEO_C", "total_applications": 0})

    df = pd.DataFrame(data)
    engine = MockEngine()

    results = calculate_risk_and_predict(df, engine)

    if not results.empty:
        geo_c = results[results["geo_code"] == "GEO_C"]
        if not geo_c.empty:
            assert geo_c.iloc[-1]["risk_score_calculated"] == 0


def test_reuse_model_when_data_signature_matches(monkeypatch):
    dates = pd.date_range(start="2023-01-01", periods=15, freq="MS")
    data = [{"date": d, "geo_code": "GEO_REUSE", "total_applications": 50 + i} for i, d in enumerate(dates)]
    df = pd.DataFrame(data)

    reused_model = DummyModel(value=12.0)
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
    monkeypatch.setattr(rp, "compute_data_signature", lambda df: reuse_signature)
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
    assert all(results["predicted_risk_score"] == reused_model.value)

    # Direct call still reports reuse
    model, model_id, info = rp.get_or_train_model(
        engine,
        "GEO_REUSE",
        df.assign(
            risk_score=1.0,
            lag_1=1.0,
            lag_2=1.0,
            lag_3=1.0,
            month=df["date"].dt.month,
        ),
    )

    assert model is reused_model
    assert model_id == 99
    assert info["reused"] is True


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
        "lag_2": [1, 2, 3],
        "lag_3": [1, 2, 3],
        "month": [1, 2, 3],
        "risk_score": [4.0, 6.0, 8.0],
    })
    model = DummyModel(value=5.0)
    # Predictions are constant 5; absolute errors are |4-5|, |6-5|, |8-5| = 1, 1, 3 → mean = 5/3
    assert evaluate_model_holdout(test_df, model) == pytest.approx(5 / 3)


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
