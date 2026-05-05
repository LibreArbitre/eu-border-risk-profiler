import logging
import os
from typing import Any, Dict, List, Optional

from fastapi import Depends, FastAPI, Header, HTTPException, Query, status
from sqlalchemy import create_engine, text

from api_service.models import CurrentRiskResponse, HistoryPoint, RiskPredictionResponse


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


def _build_database_url() -> str:
    explicit = os.getenv("DATABASE_URL")
    if explicit:
        return explicit
    user = require_env("DB_USER")
    password = require_env("DB_PASSWORD")
    name = require_env("DB_NAME")
    host = require_env("DB_HOST")
    port = require_env("DB_PORT", "5432")
    return f"postgresql://{user}:{password}@{host}:{port}/{name}"


DATABASE_URL = _build_database_url()
engine = create_engine(DATABASE_URL, pool_pre_ping=True)

# Optional API key. When unset, the API stays open (matches the previous
# behavior so single-host docker-compose deployments don't break). When set,
# every protected endpoint must echo it via the X-API-Key header.
API_KEY = os.getenv("API_KEY") or None


def require_api_key(x_api_key: Optional[str] = Header(default=None)) -> None:
    if API_KEY is None:
        return
    if x_api_key != API_KEY:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API key",
            headers={"WWW-Authenticate": "ApiKey"},
        )


def _months_between(start_value, end_value) -> int:
    """Return month delta between two date-like values (date, datetime, or ISO string)."""
    from datetime import date, datetime

    def _to_date(v):
        if isinstance(v, str):
            return datetime.fromisoformat(v).date()
        if isinstance(v, datetime):
            return v.date()
        if isinstance(v, date):
            return v
        raise TypeError(f"Unsupported date value: {v!r}")

    start = _to_date(start_value)
    end = _to_date(end_value)
    return (end.year - start.year) * 12 + (end.month - start.month)


def _select_best_snapshot(conn) -> Optional[Dict[str, Any]]:
    """Pick the prediction batch with the highest row count, breaking ties by most recent prediction_date."""
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
    row = conn.execute(snapshot_query).fetchone()
    if not row:
        return None
    return {
        "run_id": row.run_id,
        "prediction_date": row.prediction_date,
        "row_count": row.row_count,
    }


def _fetch_snapshot_rows(conn, run_id: str):
    query = text(
        """
        SELECT geo_code, date, prediction_target_month,
               risk_score_calculated, predicted_risk_score,
               predicted_risk_score_p10, predicted_risk_score_p90
        FROM risk_predictions
        WHERE run_id = :run_id AND predicted_risk_score IS NOT NULL
        ORDER BY geo_code, prediction_target_month
        """
    )
    return conn.execute(query, {"run_id": run_id}).fetchall()


def _maybe_float(value):
    """Coerce a possibly-NULL numeric DB value into a Python float or None."""
    return float(value) if value is not None else None


@app.get("/health")
def healthcheck():
    """Healthcheck endpoint verifying DB connectivity."""
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return {"status": "ok"}
    except Exception as exc:
        logger.exception("Healthcheck failed", extra={"event": "healthcheck_error"})
        raise HTTPException(status_code=503, detail=str(exc))


@app.get(
    "/api/v1/risk/current",
    response_model=List[CurrentRiskResponse],
    dependencies=[Depends(require_api_key)],
)
@app.get(
    "/api/v1/risk/latest",
    response_model=List[CurrentRiskResponse],
    dependencies=[Depends(require_api_key)],
)
def get_current_risk(
    threshold: Optional[float] = Query(
        None, ge=0, description="Include only predictions with a risk score at or below this value."
    ),
    horizon: Optional[int] = Query(
        None,
        ge=1,
        le=3,
        description="Predictive horizon in months (1, 2, or 3 — i.e. M+1, M+2, M+3).",
    ),
):
    """Return the most recent completed set of predictions with optional filtering.

    The query selects the prediction batch with the highest row count (most complete),
    falling back to the latest batch when counts tie. Clients can optionally filter
    predictions by a maximum risk score (`threshold`) and by predictive horizon.
    The horizon is computed from the difference between the source month (`date`)
    and the `prediction_target_month`.
    """
    try:
        with engine.connect() as conn:
            snapshot = _select_best_snapshot(conn)
            if not snapshot:
                logger.warning("No predictions found", extra={"event": "current_risk_not_found"})
                raise HTTPException(status_code=404, detail="No predictions found")
            rows = _fetch_snapshot_rows(conn, snapshot["run_id"])

        results: List[Dict[str, Any]] = []
        for row in rows:
            horizon_months = _months_between(row.date, row.prediction_target_month)
            score = float(row.predicted_risk_score)

            if horizon is not None and horizon_months != horizon:
                continue
            if threshold is not None and score > threshold:
                continue

            base = float(row.risk_score_calculated) if row.risk_score_calculated is not None else None
            pct_change = ((score - base) / base * 100.0) if base else None

            results.append(
                {
                    "geo_code": row.geo_code,
                    "risk_score": score,
                    "risk_score_p10": _maybe_float(getattr(row, "predicted_risk_score_p10", None)),
                    "risk_score_p90": _maybe_float(getattr(row, "predicted_risk_score_p90", None)),
                    "prediction_target_month": row.prediction_target_month,
                    "horizon_months": int(horizon_months),
                    "percent_change": pct_change,
                    "type": "predicted",
                }
            )

        if not results:
            logger.warning(
                "No predictions match filters",
                extra={"event": "current_risk_filtered_empty", "horizon": horizon, "threshold": threshold},
            )
            raise HTTPException(status_code=404, detail="No predictions match the requested filters")

        return results
    except HTTPException:
        raise
    except Exception:
        logger.exception(
            "Failed to fetch current risk predictions",
            extra={"event": "current_risk_error", "horizon": horizon, "threshold": threshold},
        )
        raise HTTPException(status_code=500, detail="Failed to fetch current risk predictions")


@app.get(
    "/api/v1/risk/predict",
    response_model=List[RiskPredictionResponse],
    dependencies=[Depends(require_api_key)],
)
def get_predictions():
    """Returns predictions (M+1..M+3) drawn from the most complete recent snapshot."""
    try:
        with engine.connect() as conn:
            snapshot = _select_best_snapshot(conn)
            if not snapshot:
                logger.warning("No predictions found", extra={"event": "predictions_not_found"})
                raise HTTPException(status_code=404, detail="No predictions found")
            rows = _fetch_snapshot_rows(conn, snapshot["run_id"])

        return [
            {
                "geo_code": r.geo_code,
                "risk_score_calculated": float(r.risk_score_calculated),
                "predicted_risk_score": float(r.predicted_risk_score),
                "predicted_risk_score_p10": _maybe_float(getattr(r, "predicted_risk_score_p10", None)),
                "predicted_risk_score_p90": _maybe_float(getattr(r, "predicted_risk_score_p90", None)),
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


@app.get(
    "/api/v1/data/history/{geo_code}",
    response_model=List[HistoryPoint],
    dependencies=[Depends(require_api_key)],
)
def get_history(geo_code: str):
    """Returns raw applications count for line chart, aggregated by date."""
    query = text(
        """
        SELECT date, SUM(total_applications) AS total_applications
        FROM asylum_data
        WHERE geo_code = :geo AND applicant_type = 'FRST'
        GROUP BY date
        ORDER BY date
        """
    )
    try:
        with engine.connect() as conn:
            rows = conn.execute(query, {"geo": geo_code}).fetchall()
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
