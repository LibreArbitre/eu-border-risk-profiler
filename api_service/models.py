from datetime import date
from typing import Optional
from pydantic import BaseModel

class RiskPredictionResponse(BaseModel):
    """
    Schema for risk prediction data.

    ``predicted_risk_score`` is the mean of the underlying RandomForest's
    per-tree predictions. ``predicted_risk_score_p10`` /
    ``predicted_risk_score_p90`` are the 10th and 90th percentiles of the
    same per-tree distribution and are nullable for backwards compatibility
    with predictions persisted before quantiles were captured.
    """
    geo_code: str
    risk_score_calculated: float
    predicted_risk_score: float
    predicted_risk_score_p10: Optional[float] = None
    predicted_risk_score_p90: Optional[float] = None
    date: date
    prediction_target_month: date
    type: str = "predicted"

class HistoryPoint(BaseModel):
    """
    Schema for historical data points.
    """
    date: date
    total: int

class CurrentRiskResponse(BaseModel):
    """
    Schema for current/latest risk assessment with analysis.

    ``risk_score_p10`` and ``risk_score_p90`` mirror the quantile band
    exposed in :class:`RiskPredictionResponse` and are likewise nullable.
    """
    geo_code: str
    risk_score: float
    risk_score_p10: Optional[float] = None
    risk_score_p90: Optional[float] = None
    prediction_target_month: date
    horizon_months: int
    percent_change: Optional[float] = None
    type: str = "predicted"
