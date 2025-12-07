import os
from typing import Optional, List
from fastapi import FastAPI, HTTPException, Query
from sqlalchemy import create_engine, text
from models import RiskPredictionResponse, HistoryPoint, CurrentRiskResponse

app = FastAPI(title="EU Border Risk Profiler API")

DB_USER = os.getenv("DB_USER", "user")
DB_PASSWORD = os.getenv("DB_PASSWORD", "password")
DB_NAME = os.getenv("DB_NAME", "eubrp_db")
DB_HOST = os.getenv("DB_HOST", "db")
DB_PORT = os.getenv("DB_PORT", "5432")
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


@app.get("/api/v1/risk/current", response_model=List[CurrentRiskResponse])
@app.get("/api/v1/risk/latest", response_model=List[CurrentRiskResponse])
def get_current_risk(
    threshold: Optional[float] = Query(
        None, ge=0, description="Exclude predictions with a risk score above this value."
    ),
    horizon: Optional[int] = Query(
        None,
        ge=1,
        le=3,
        description="Predictive horizon in months (M+1, M+2, or M+3).",
    ),
):
    """Return the most recent completed set of predictions with optional filtering.

    The query selects the prediction batch with the highest row count (most complete),
    falling back to the latest batch when counts tie. Clients can optionally filter
    predictions by a maximum risk score (`threshold`) and by predictive horizon (`horizon`).
    The predictive horizon is computed from the difference between the source month
    (`date`) and the `prediction_target_month`.
    """

    query = text(
        """
        WITH snapshot AS (
            SELECT
                prediction_date,
                COUNT(*) AS row_count
            FROM risk_predictions
            WHERE predicted_risk_score IS NOT NULL
            GROUP BY prediction_date
        ),
        selected_snapshot AS (
            SELECT prediction_date
            FROM snapshot
            ORDER BY row_count DESC, prediction_date DESC
            LIMIT 1
        ),
        latest_predictions AS (
            SELECT
                rp.geo_code,
                rp.predicted_risk_score,
                rp.prediction_target_month,
                rp.date,
                (
                    (EXTRACT(YEAR FROM rp.prediction_target_month) * 12 + EXTRACT(MONTH FROM rp.prediction_target_month))
                    - (EXTRACT(YEAR FROM rp.date) * 12 + EXTRACT(MONTH FROM rp.date))
                ) AS horizon_months,
                LAG(rp.predicted_risk_score) OVER (
                    PARTITION BY rp.geo_code
                    ORDER BY rp.prediction_target_month
                ) AS previous_score
            FROM risk_predictions rp
            JOIN selected_snapshot ss ON rp.prediction_date = ss.prediction_date
            WHERE rp.predicted_risk_score IS NOT NULL
        )
        SELECT
            geo_code,
            predicted_risk_score AS score,
            prediction_target_month,
            horizon_months,
            CASE
                WHEN previous_score IS NULL OR previous_score = 0 THEN NULL
                ELSE ((predicted_risk_score - previous_score) / previous_score) * 100
            END AS pct_change
        FROM latest_predictions
        WHERE (:horizon IS NULL OR horizon_months = :horizon)
          AND (:threshold IS NULL OR predicted_risk_score <= :threshold)
        ORDER BY geo_code, prediction_target_month
        """
    )

    try:
        with engine.connect() as conn:
            result = conn.execute(query, {"horizon": horizon, "threshold": threshold})
            rows = result.fetchall()
            if not rows:
                raise HTTPException(status_code=404, detail="No predictions found")

            return [
                {
                    "geo_code": row.geo_code,
                    "risk_score": float(row.score),
                    "prediction_target_month": row.prediction_target_month,
                    "horizon_months": int(row.horizon_months),
                    "percent_change": float(row.pct_change) if row.pct_change is not None else None,
                    "type": "predicted",
                }
                for row in rows
            ]
    except HTTPException:
        raise
    except Exception as exc:  # pragma: no cover - runtime behavior
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/api/v1/risk/predict", response_model=List[RiskPredictionResponse])
def get_predictions():
    """Returns predictions for M+1..M+3."""
    # Logic: Get predictions from the latest run
    query = """
    WITH latest_date_per_geo AS (
        SELECT geo_code, MAX(date) as max_date
        FROM risk_predictions
        GROUP BY geo_code
    )
    SELECT rp.geo_code, rp.risk_score_calculated, rp.predicted_risk_score, rp.date, rp.prediction_target_month
    FROM risk_predictions rp
    JOIN latest_date_per_geo ld ON rp.geo_code = ld.geo_code AND rp.date = ld.max_date
    """
    try:
        with engine.connect() as conn:
            result = conn.execute(text(query))
            return [
                {
                    "geo_code": r.geo_code,
                    "risk_score_calculated": float(r.risk_score_calculated),
                    "predicted_risk_score": float(r.predicted_risk_score),
                    "date": r.date,
                    "prediction_target_month": r.prediction_target_month,
                    "type": "predicted",
                }
                for r in result
            ]
    except Exception as e:
        print(e)
        return []


@app.get("/api/v1/data/history/{geo_code}", response_model=List[HistoryPoint])
def get_history(geo_code: str):
    """Returns raw applications count for line chart, aggregated by date."""
    query = text(
        """
        SELECT date, SUM(total_applications) as total_applications 
        FROM asylum_data 
        WHERE geo_code = :geo AND applicant_type='FRST' 
        GROUP BY date 
        ORDER BY date
        """
    )
    try:
        with engine.connect() as conn:
            result = conn.execute(query, {"geo": geo_code})
            return [{"date": r.date, "total": int(r.total_applications)} for r in result]
    except Exception as e:
        print(e)
        return []
