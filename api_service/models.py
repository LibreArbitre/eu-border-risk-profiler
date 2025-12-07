# Fichier: api_service/models.py
from datetime import date
from typing import Optional

from pydantic import BaseModel


class RiskPrediction(BaseModel):
    """
    Modèle Pydantic pour les résultats de la prédiction des risques.
    """

    geo_code: str
    prediction_target_month: date
    predicted_risk_score: float
    model_version: Optional[str] = None
    prediction_date: date
