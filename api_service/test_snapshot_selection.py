import importlib
from datetime import datetime

import pytest
from sqlalchemy import create_engine, text

SCHEMA_SQL = """
CREATE TABLE risk_predictions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date DATE NOT NULL,
    geo_code VARCHAR(10) NOT NULL,
    risk_score_calculated REAL NOT NULL,
    prediction_target_month DATE NOT NULL,
    predicted_risk_score REAL,
    predicted_risk_score_p10 REAL,
    predicted_risk_score_p90 REAL,
    model_id INTEGER,
    prediction_date TIMESTAMP NOT NULL,
    run_id VARCHAR(64) NOT NULL
);
"""


@pytest.fixture()
def app_module(tmp_path, monkeypatch):
    db_url = f"sqlite:///{tmp_path/'api_test.db'}"
    monkeypatch.setenv("DATABASE_URL", db_url)

    # Reload module to pick up new DATABASE_URL
    import api_service.main as main
    importlib.reload(main)

    engine = create_engine(db_url)
    with engine.begin() as conn:
        conn.execute(text(SCHEMA_SQL))
    main.engine = engine

    yield main


def insert_predictions(engine, rows):
    insert_sql = text(
        """
        INSERT INTO risk_predictions (
            date, geo_code, risk_score_calculated, prediction_target_month,
            predicted_risk_score, model_id, prediction_date, run_id
        ) VALUES (
            :date, :geo_code, :risk_score_calculated, :prediction_target_month,
            :predicted_risk_score, :model_id, :prediction_date, :run_id
        )
        """
    )
    with engine.begin() as conn:
        for row in rows:
            conn.execute(insert_sql, row)


def test_selects_most_complete_snapshot(app_module):
    engine = app_module.engine

    insert_predictions(
        engine,
        [
            {
                "date": datetime(2024, 1, 1),
                "geo_code": "FR",
                "risk_score_calculated": 10.0,
                "prediction_target_month": datetime(2024, 2, 1),
                "predicted_risk_score": 20.0,
                "model_id": 1,
                "prediction_date": datetime(2024, 2, 15),
                "run_id": "run-old",
            },
            {
                "date": datetime(2024, 1, 1),
                "geo_code": "FR",
                "risk_score_calculated": 10.0,
                "prediction_target_month": datetime(2024, 2, 1),
                "predicted_risk_score": 30.0,
                "model_id": 1,
                "prediction_date": datetime(2024, 3, 1),
                "run_id": "run-new",
            },
            {
                "date": datetime(2024, 1, 1),
                "geo_code": "DE",
                "risk_score_calculated": 11.0,
                "prediction_target_month": datetime(2024, 2, 1),
                "predicted_risk_score": 40.0,
                "model_id": 1,
                "prediction_date": datetime(2024, 3, 1),
                "run_id": "run-new",
            },
        ],
    )

    results = app_module.get_current_risk(threshold=None, horizon=None)
    scores = sorted((row["geo_code"], row["risk_score"]) for row in results)

    assert scores == [("DE", 40.0), ("FR", 30.0)]


def test_get_predictions_uses_same_snapshot(app_module):
    engine = app_module.engine

    insert_predictions(
        engine,
        [
            {
                "date": datetime(2024, 1, 1),
                "geo_code": "FR",
                "risk_score_calculated": 10.0,
                "prediction_target_month": datetime(2024, 2, 1),
                "predicted_risk_score": 50.0,
                "model_id": 1,
                "prediction_date": datetime(2024, 3, 10),
                "run_id": "run-a",
            },
            {
                "date": datetime(2024, 1, 1),
                "geo_code": "DE",
                "risk_score_calculated": 11.0,
                "prediction_target_month": datetime(2024, 2, 1),
                "predicted_risk_score": 60.0,
                "model_id": 1,
                "prediction_date": datetime(2024, 3, 10),
                "run_id": "run-a",
            },
            {
                "date": datetime(2024, 1, 1),
                "geo_code": "FR",
                "risk_score_calculated": 10.0,
                "prediction_target_month": datetime(2024, 2, 1),
                "predicted_risk_score": 70.0,
                "model_id": 1,
                "prediction_date": datetime(2024, 3, 11),
                "run_id": "run-b",
            },
            {
                "date": datetime(2024, 1, 1),
                "geo_code": "DE",
                "risk_score_calculated": 11.0,
                "prediction_target_month": datetime(2024, 2, 1),
                "predicted_risk_score": 80.0,
                "model_id": 1,
                "prediction_date": datetime(2024, 3, 11),
                "run_id": "run-b",
            },
        ],
    )

    results = app_module.get_predictions()
    scores = sorted((row["geo_code"], row["predicted_risk_score"]) for row in results)

    assert scores == [("DE", 80.0), ("FR", 70.0)]


def _batch(run_id, prediction_date, geo_codes, score=10.0):
    """Build one prediction batch (one row per geo code)."""
    return [
        {
            "date": datetime(2024, 1, 1),
            "geo_code": geo,
            "risk_score_calculated": 5.0,
            "prediction_target_month": datetime(2024, 2, 1),
            "predicted_risk_score": score,
            "model_id": 1,
            "prediction_date": prediction_date,
            "run_id": run_id,
        }
        for geo in geo_codes
    ]


def test_newer_run_wins_when_reasonably_complete(app_module):
    """A fresh batch missing one country out of ten must beat an older full batch."""
    engine = app_module.engine
    geos = ["AT", "BE", "BG", "CY", "CZ", "DE", "DK", "EE", "ES", "FR"]

    insert_predictions(
        engine,
        _batch("run-old-full", datetime(2024, 3, 1), geos, score=20.0)
        + _batch("run-new-minus-one", datetime(2024, 4, 1), geos[:-1], score=30.0),
    )

    results = app_module.get_predictions()
    assert {row["predicted_risk_score"] for row in results} == {30.0}
    assert len(results) == 9


def test_incomplete_newer_run_does_not_shadow_full_one(app_module):
    """A degenerate fresh batch (far below the completeness ratio) must lose."""
    engine = app_module.engine
    geos = ["AT", "BE", "BG", "CY", "CZ", "DE", "DK", "EE", "ES", "FR"]

    insert_predictions(
        engine,
        _batch("run-old-full", datetime(2024, 3, 1), geos, score=20.0)
        + _batch("run-new-degenerate", datetime(2024, 4, 1), geos[:2], score=30.0),
    )

    results = app_module.get_predictions()
    assert {row["predicted_risk_score"] for row in results} == {20.0}
    assert len(results) == 10


def test_threshold_keeps_scores_at_or_above(app_module):
    """?threshold= follows alerting semantics: keep the risky countries."""
    engine = app_module.engine

    insert_predictions(
        engine,
        _batch("run-a", datetime(2024, 3, 1), ["FR"], score=80.0)
        + _batch("run-a", datetime(2024, 3, 1), ["DE"], score=20.0),
    )

    results = app_module.get_current_risk(threshold=50.0, horizon=None)
    assert [(r["geo_code"], r["risk_score"]) for r in results] == [("FR", 80.0)]
