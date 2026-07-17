from datetime import datetime, timedelta

import pandas as pd
from sqlalchemy import create_engine, text

import risk_predictor.risk_predictor as risk_predictor

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

MODEL_REGISTRY_SQL = """
CREATE TABLE model_registry (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    model_name VARCHAR(100) NOT NULL,
    geo_code VARCHAR(10) NOT NULL,
    model_version VARCHAR(50) NOT NULL,
    trained_at TIMESTAMP NOT NULL,
    hyperparameters TEXT,
    model_artifact BLOB NOT NULL
);
"""


def create_test_engine():
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as conn:
        conn.execute(text(SCHEMA_SQL))
        conn.execute(text(MODEL_REGISTRY_SQL))
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


def _insert_model(engine, geo_code, trained_at, version):
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO model_registry"
                " (model_name, geo_code, model_version, trained_at, model_artifact)"
                " VALUES (:name, :geo, :version, :trained_at, :artifact)"
            ),
            {
                "name": "random_forest_risk",
                "geo": geo_code,
                "version": version,
                "trained_at": trained_at,
                "artifact": b"blob",
            },
        )


def test_purge_old_models_keeps_last_n_per_geo():
    engine = create_test_engine()
    now = datetime.utcnow()

    for geo in ("FR", "DE"):
        for i in range(4):
            _insert_model(engine, geo, now - timedelta(days=30 * i), f"v{i}")

    risk_predictor.purge_old_models(engine, keep_last=2)

    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT geo_code, model_version FROM model_registry"
                " ORDER BY geo_code, trained_at DESC"
            )
        ).fetchall()

    # Two most recent versions kept per country (v0 = newest).
    assert [(r.geo_code, r.model_version) for r in rows] == [
        ("DE", "v0"),
        ("DE", "v1"),
        ("FR", "v0"),
        ("FR", "v1"),
    ]


def test_purge_old_models_spares_referenced_models():
    engine = create_test_engine()
    now = datetime.utcnow()

    for i in range(4):
        _insert_model(engine, "FR", now - timedelta(days=30 * i), f"v{i}")

    # The OLDEST model (id 4, v3) is still referenced by a retained prediction.
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO risk_predictions"
                " (date, geo_code, risk_score_calculated, prediction_target_month,"
                "  predicted_risk_score, model_id, prediction_date, run_id)"
                " VALUES ('2024-01-01', 'FR', 10.0, '2024-02-01', 12.0, 4, :pdate, 'run-x')"
            ),
            {"pdate": now},
        )

    risk_predictor.purge_old_models(engine, keep_last=2)

    with engine.connect() as conn:
        versions = {
            r.model_version
            for r in conn.execute(text("SELECT model_version FROM model_registry")).fetchall()
        }

    # v0/v1 kept by recency, v3 kept because referenced, v2 purged.
    assert versions == {"v0", "v1", "v3"}


def test_purge_old_models_disabled_when_keep_last_zero():
    engine = create_test_engine()
    now = datetime.utcnow()
    for i in range(3):
        _insert_model(engine, "FR", now - timedelta(days=30 * i), f"v{i}")

    risk_predictor.purge_old_models(engine, keep_last=0)

    with engine.connect() as conn:
        count = conn.execute(text("SELECT COUNT(*) FROM model_registry")).scalar_one()
    assert count == 3
