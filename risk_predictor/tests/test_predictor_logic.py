from functools import partial

import pandas as pd
import pytest
import risk_predictor.risk_predictor as rp
from risk_predictor.risk_predictor import calculate_risk_and_predict, compute_data_signature, get_or_train_model


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
