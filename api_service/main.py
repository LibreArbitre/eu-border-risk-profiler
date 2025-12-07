import os
from collections import defaultdict
from datetime import date, datetime
from typing import Optional, List, Dict, Any
from fastapi import FastAPI, HTTPException, Query
from sqlalchemy import create_engine, text
from .models import RiskPredictionResponse, HistoryPoint, CurrentRiskResponse

app = FastAPI(title="EU Border Risk Profiler API")

DB_USER = os.getenv("DB_USER", "user")
DB_PASSWORD = os.getenv("DB_PASSWORD", "password")
DB_NAME = os.getenv("DB_NAME", "eubrp_db")
DB_HOST = os.getenv("DB_HOST", "db")
DB_PORT = os.getenv("DB_PORT", "5432")
DATABASE_URL = os.getenv(
    "DATABASE_URL", f"postgresql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
)

engine = create_engine(DATABASE_URL)


def _coerce_date(value):
    if isinstance(value, str):
        return datetime.fromisoformat(value).date()
    if isinstance(value, datetime):
        return value.date()
    return value


def _months_between(start_date: date, end_date: date) -> int:
    start = _coerce_date(start_date)
    end = _coerce_date(end_date)
    return (end.year - start.year) * 12 + (end.month - start.month)


def _select_best_snapshot(conn) -> Optional[Dict[str, Any]]:
    snapshot_query = text(
        """
        SELECT run_id, MAX(prediction_date) AS prediction_date, COUNT(*) AS row_count
        FROM risk_predictions
        WHERE predicted_risk_score IS NOT NULL
        GROUP BY run_id
        ORDER BY row_count DESC, prediction_date DESC
        LIMIT 1
        """
    )
    result = conn.execute(snapshot_query).fetchone()
    if not result:
        return None

    return {
        "run_id": result.run_id,
        "prediction_date": result.prediction_date,
        "row_count": result.row_count,
    }


def _fetch_predictions_for_run(conn, run_id: str):
    query = text(
        """
        SELECT geo_code, predicted_risk_score, prediction_target_month, date
        FROM risk_predictions
        WHERE run_id = :run_id AND predicted_risk_score IS NOT NULL
        ORDER BY geo_code, prediction_target_month
        """
    )
    return conn.execute(query, {"run_id": run_id}).fetchall()


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

    try:
        with engine.connect() as conn:
            snapshot = _select_best_snapshot(conn)
            if not snapshot:
                raise HTTPException(status_code=404, detail="No predictions found")

            rows = _fetch_predictions_for_run(conn, snapshot["run_id"])
            if not rows:
                raise HTTPException(status_code=404, detail="No predictions found")

            previous_scores: Dict[str, Optional[float]] = defaultdict(lambda: None)
            response = []

            for row in rows:
                horizon_months = _months_between(row.date, row.prediction_target_month)
                pct_change = None
                prev_score = previous_scores[row.geo_code]
                if prev_score not in (None, 0):
                    pct_change = ((row.predicted_risk_score - prev_score) / prev_score) * 100

                previous_scores[row.geo_code] = row.predicted_risk_score

                if horizon is not None and horizon_months != horizon:
                    continue
                if threshold is not None and row.predicted_risk_score > threshold:
                    continue

                response.append(
                    {
                        "geo_code": row.geo_code,
                        "risk_score": float(row.predicted_risk_score),
                        "prediction_target_month": row.prediction_target_month,
                        "horizon_months": int(horizon_months),
                        "percent_change": float(pct_change) if pct_change is not None else None,
                        "type": "predicted",
                    }
                )

            if not response:
                raise HTTPException(status_code=404, detail="No predictions found")

            return response
    except HTTPException:
        raise
    except Exception as exc:  # pragma: no cover - runtime behavior
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/api/v1/risk/predict", response_model=List[RiskPredictionResponse])
def get_predictions():
    """Returns predictions for M+1..M+3."""
    try:
        with engine.connect() as conn:
            snapshot = _select_best_snapshot(conn)
            if not snapshot:
                raise HTTPException(status_code=404, detail="No predictions found")

            query = text(
                """
                SELECT geo_code, risk_score_calculated, predicted_risk_score, date, prediction_target_month
                FROM risk_predictions
                WHERE run_id = :run_id
                ORDER BY geo_code, prediction_target_month
                """
            )
            result = conn.execute(query, {"run_id": snapshot["run_id"]})
            rows = result.fetchall()
            if not rows:
                raise HTTPException(status_code=404, detail="No predictions found")

            return [
                {
                    "geo_code": r.geo_code,
                    "risk_score_calculated": float(r.risk_score_calculated),
                    "predicted_risk_score": float(r.predicted_risk_score),
                    "date": r.date,
                    "prediction_target_month": r.prediction_target_month,
                    "type": "predicted",
                }
                for r in rows
            ]
    except HTTPException:
        raise
    except Exception as exc:  # pragma: no cover - runtime behavior
        raise HTTPException(status_code=500, detail=str(exc))


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
