import logging
import os
from datetime import date, datetime
from typing import Optional, List, Dict, Any
from fastapi import Depends, FastAPI, HTTPException, Query
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker
from api_service.models import RiskPredictionResponse, HistoryPoint, CurrentRiskResponse


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("api_service")

app = FastAPI(title="EU Border Risk Profiler API")


def require_env(var_name: str, default: Optional[str] = None) -> str:
    """Return environment variable value, or a default if provided."""

    value = os.getenv(var_name, default)
    if value in (None, ""):
        logger.error("Missing required environment variable", extra={"env_var": var_name})
        raise RuntimeError(f"Missing required environment variable: {var_name}")
    return value


DB_USER = require_env("DB_USER")
DB_PASSWORD = require_env("DB_PASSWORD")
DB_NAME = require_env("DB_NAME")
DB_HOST = require_env("DB_HOST")
DB_PORT = require_env("DB_PORT", "5432")
DATABASE_URL = f"postgresql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"

engine = create_engine(DATABASE_URL, pool_size=20, max_overflow=10)
SessionLocal = sessionmaker(bind=engine)


def get_db_session():
    """Provide a SQLAlchemy session with structured logging and cleanup."""

    session: Session = SessionLocal()
    logger.info("Opening database session", extra={"event": "db_session_open"})
    try:
        yield session
    except Exception:
        logger.exception("Database session error", extra={"event": "db_session_error"})
        raise
    finally:
        session.close()
        logger.info("Closed database session", extra={"event": "db_session_close"})


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
def healthcheck(session: Session = Depends(get_db_session)):
    """Healthcheck endpoint verifying DB connectivity."""

    try:
        session.execute(text("SELECT 1"))
        return {"status": "ok"}
    except Exception as exc:  # pragma: no cover - used for runtime checks
        logger.exception("Healthcheck failed", extra={"event": "healthcheck_error"})
        raise HTTPException(status_code=503, detail=str(exc))


@app.get("/api/v1/risk/current", response_model=List[CurrentRiskResponse])
@app.get("/api/v1/risk/latest", response_model=List[CurrentRiskResponse])
def get_current_risk(
    threshold: Optional[float] = Query(
        None, ge=0, le=100, description="Exclude predictions with a risk score above this value."
    ),
    horizon: Optional[int] = Query(
        None,
        ge=1,
        le=3,
        description="Predictive horizon in months (M+1, M+2, or M+3).",
    ),
    session: Session = Depends(get_db_session),
):
    """Return the most recent completed set of predictions with optional filtering.

    The query selects the prediction batch with the highest row count (most complete),
    falling back to the latest batch when counts tie. Clients can optionally filter
    predictions by a maximum risk score (`threshold`) and by predictive horizon (`horizon`).
    The predictive horizon is computed from the difference between the source month
    (`date`) and the `prediction_target_month`.
    """

    try:
        snapshot = _select_best_snapshot(session)
        if not snapshot:
            logger.warning("No predictions found", extra={"event": "current_risk_not_found"})
            raise HTTPException(status_code=404, detail="No predictions found")

        query = text(
            """
            SELECT
                geo_code,
                predicted_risk_score AS score,
                prediction_target_month,
                (EXTRACT(YEAR FROM prediction_target_month) - EXTRACT(YEAR FROM date)) * 12
                + (EXTRACT(MONTH FROM prediction_target_month) - EXTRACT(MONTH FROM date))
                AS horizon_months,
                NULL::float AS pct_change
            FROM risk_predictions
            WHERE run_id = :run_id
              AND predicted_risk_score IS NOT NULL
              AND (:threshold IS NULL OR predicted_risk_score <= :threshold)
              AND (
                  :horizon IS NULL
                  OR (EXTRACT(YEAR FROM prediction_target_month) - EXTRACT(YEAR FROM date)) * 12
                     + (EXTRACT(MONTH FROM prediction_target_month) - EXTRACT(MONTH FROM date))
                     = :horizon
              )
            ORDER BY geo_code, prediction_target_month
            """
        )
        result = session.execute(query, {"run_id": snapshot["run_id"], "horizon": horizon, "threshold": threshold})
        rows = result.fetchall()
        if not rows:
            logger.warning("No predictions found", extra={"event": "current_risk_not_found"})
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
    except Exception:
        logger.exception(
            "Failed to fetch current risk predictions",
            extra={"event": "current_risk_error", "horizon": horizon, "threshold": threshold},
        )
        raise HTTPException(status_code=500, detail="Failed to fetch current risk predictions")


@app.get("/api/v1/risk/predict", response_model=List[RiskPredictionResponse])
def get_predictions(session: Session = Depends(get_db_session)):
    """Returns predictions for M+1..M+3."""
    try:
        snapshot = _select_best_snapshot(session)
        if not snapshot:
            logger.warning("No predictions found", extra={"event": "predictions_not_found"})
            raise HTTPException(status_code=404, detail="No predictions found")

        query = text(
            """
            SELECT geo_code, risk_score_calculated, predicted_risk_score, date, prediction_target_month
            FROM risk_predictions
            WHERE run_id = :run_id AND predicted_risk_score IS NOT NULL
            ORDER BY geo_code, prediction_target_month
            """
        )
        result = session.execute(query, {"run_id": snapshot["run_id"]})
        rows = result.fetchall()
        if not rows:
            logger.warning("No predictions found", extra={"event": "predictions_not_found"})
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
    except Exception:
        logger.exception("Failed to fetch predictions", extra={"event": "predictions_error"})
        raise HTTPException(status_code=500, detail="Failed to fetch predictions")


@app.get("/api/v1/data/history/{geo_code}", response_model=List[HistoryPoint])
def get_history(geo_code: str, session: Session = Depends(get_db_session)):
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
        result = session.execute(query, {"geo": geo_code})
        rows = result.fetchall()
        if not rows:
            logger.warning(
                "No history found for geo code", extra={"event": "history_not_found", "geo_code": geo_code}
            )
            raise HTTPException(status_code=404, detail="No history found")

        return [{"date": r.date, "total": int(r.total_applications)} for r in rows]
    except HTTPException:
        raise
    except Exception:
        logger.exception("Failed to fetch history", extra={"event": "history_error", "geo_code": geo_code})
        raise HTTPException(status_code=500, detail="Failed to fetch history")
