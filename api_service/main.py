from fastapi import FastAPI, HTTPException
from sqlalchemy import create_engine, text
from pydantic import BaseModel
from typing import List, Optional
from datetime import date
import os
import pandas as pd

app = FastAPI(title="EU Border Risk Profiler API")

DB_USER = os.getenv('DB_USER', 'user')
DB_PASSWORD = os.getenv('DB_PASSWORD', 'password')
DB_NAME = os.getenv('DB_NAME', 'eubrp_db')
DB_HOST = os.getenv('DB_HOST', 'db')
DB_PORT = os.getenv('DB_PORT', '5432')
DATABASE_URL = f"postgresql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"

engine = create_engine(DATABASE_URL)


@app.get("/health")
def healthcheck():
    """Healthcheck endpoint verifying DB connectivity."""
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return {"status": "ok"}
    except Exception as exc:  # pragma: no cover - used for runtime checks
        raise HTTPException(status_code=503, detail=str(exc))

@app.get("/api/v1/risk/latest")
def get_latest_risk():
    """Returns the latest calculated risk score for each country."""
    query = """
    SELECT DISTINCT ON (geo_code) geo_code, risk_score_calculated as score, date
    FROM risk_predictions
    ORDER BY geo_code, date DESC
    """
    try:
        with engine.connect() as conn:
            result = conn.execute(text(query))
            return [{"geo_code": r.geo_code, "risk_score": float(r.score), "date": r.date, "type": "observed"} for r in result]
    except Exception as e:
        print(e)
        return []

@app.get("/api/v1/risk/predict")
def get_predictions():
    """Returns predictions for M+1..M+3."""
    # Logic: Get predictions from the latest run
    query = """
    SELECT geo_code, predicted_risk_score as score, prediction_target_month as date
    FROM risk_predictions
    WHERE date = (SELECT MAX(date) FROM risk_predictions)
    """
    try:
        with engine.connect() as conn:
            result = conn.execute(text(query))
            return [{"geo_code": r.geo_code, "risk_score": float(r.score), "date": r.date, "type": "predicted"} for r in result]
    except Exception as e:
        print(e)
        return []

@app.get("/api/v1/data/history/{geo_code}")
def get_history(geo_code: str):
    """Returns raw applications count for line chart."""
    query = text(
        "SELECT date, total_applications FROM asylum_data WHERE geo_code = :geo AND applicant_type='FRST' ORDER BY date"
    )
    try:
        with engine.connect() as conn:
            result = conn.execute(query, {"geo": geo_code})
            return [{"date": r.date, "total": r.total_applications} for r in result]
    except Exception as e:
        print(e)
        return []
