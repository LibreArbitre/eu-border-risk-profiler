import pandas as pd
from datetime import datetime, timedelta
from sqlalchemy import create_engine, text

import risk_predictor


SCHEMA_SQL = """
CREATE TABLE risk_predictions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date DATE NOT NULL,
    geo_code VARCHAR(10) NOT NULL,
    risk_score_calculated REAL NOT NULL,
    prediction_target_month DATE NOT NULL,
    predicted_risk_score REAL,
    model_id INTEGER,
    prediction_date TIMESTAMP NOT NULL,
    run_id VARCHAR(64) NOT NULL
);
"""


def create_test_engine():
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as conn:
        conn.execute(text(SCHEMA_SQL))
    return engine


def base_predictions():
    return pd.DataFrame(
        [
            {
                "date": datetime(2024, 1, 1),
                "geo_code": "FR",
                "risk_score_calculated": 10.0,
                "prediction_target_month": datetime(2024, 2, 1),
                "predicted_risk_score": 12.5,
                "model_id": 1,
            },
            {
                "date": datetime(2024, 1, 1),
                "geo_code": "DE",
                "risk_score_calculated": 11.0,
                "prediction_target_month": datetime(2024, 2, 1),
                "predicted_risk_score": 13.5,
                "model_id": 1,
            },
        ]
    )


def test_append_runs_without_truncate():
    engine = create_test_engine()

    df = base_predictions()
    risk_predictor.save_predictions(df, engine=engine, run_metadata={"run_id": "run-1"})
    risk_predictor.save_predictions(df, engine=engine, run_metadata={"run_id": "run-2"})

    with engine.connect() as conn:
        counts = conn.execute(text("SELECT COUNT(*) FROM risk_predictions")).scalar_one()
        run_ids = conn.execute(text("SELECT DISTINCT run_id FROM risk_predictions ORDER BY run_id"))
        run_id_list = [row[0] for row in run_ids]

    assert counts == 4
    assert run_id_list == ["run-1", "run-2"]


def test_retention_removes_old_runs(monkeypatch):
    engine = create_test_engine()

    old_metadata = {
        "run_id": "old-run",
        "prediction_date": datetime.utcnow() - timedelta(days=10),
    }
    new_metadata = {"run_id": "new-run", "prediction_date": datetime.utcnow()}

    monkeypatch.setattr(risk_predictor, "PREDICTION_RETENTION_DAYS", 7)

    df = base_predictions()

    risk_predictor.save_predictions(df, engine=engine, run_metadata=old_metadata)
    risk_predictor.save_predictions(df, engine=engine, run_metadata=new_metadata)

    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT run_id, prediction_date FROM risk_predictions ORDER BY run_id"
            )
        ).fetchall()

    assert len(rows) == 2
    assert all(row.run_id == "new-run" for row in rows)
