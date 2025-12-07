from datetime import date
from typing import Optional
from pydantic import BaseModel

class RiskPredictionResponse(BaseModel):
    """
    Schema for risk prediction data.
    """
    geo_code: str
    risk_score_calculated: float
    predicted_risk_score: float
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
    """
    geo_code: str
    risk_score: float
    prediction_target_month: date
    horizon_months: int
    percent_change: Optional[float] = None
    type: str = "predicted"
