
import pytest
import pandas as pd
import numpy as np
from datetime import datetime
import sys
import os

# Allow import from parent directory
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from risk_predictor import calculate_risk_and_predict

class MockEngine:
    """Mock SQLAlchemy Engine for testing"""
    def connect(self):
        return self
    def begin(self):
        return self
    def __enter__(self):
        return self
    def __exit__(self, exc_type, exc_val, exc_tb):
        pass
    def execute(self, statement, params=None):
        return MockResult()

class MockResult:
    def scalar(self):
        return 1 # Mock model_id
    def fetchone(self):
        return None # Mock no existing model

def test_risk_calculation_nominal():
    """
    Test nominal risk calculation:
    - Geo A: Low, Stable
    - Geo B: High, Increasing
    """
    
    # Create synthetic history
    dates = pd.date_range(start="2023-01-01", periods=15, freq="MS") # 15 months > 12 requirement
    
    data = []
    
    # Geo A: 100 applications every month (Stable)
    for d in dates:
        data.append({
            "date": d,
            "geo_code": "GEO_A",
            "total_applications": 100
        })
        
    # Geo B: Starts at 1000, increases by 100 every month (Increasing)
    # Month 0: 1000
    # Month 1: 1100 (+10% increase)
    for i, d in enumerate(dates):
        data.append({
            "date": d,
            "geo_code": "GEO_B",
            "total_applications": 1000 + (i * 100)
        })
        
    df = pd.DataFrame(data)
    engine = MockEngine()
    
    # We execute the function
    # Note: The function will train a model, so it might be slow if we don't mock train_model, 
    # but for unit test on 'calculate_risk' logic, we are more interested in the 'calculated_risk_score' output.
    
    results = calculate_risk_and_predict(df, engine)
    
    assert not results.empty
    
    # Check Geo A (Stable)
    # Variation should be 0.
    # Score = Log(100) / GlobalMax * (1 + 0) * 100
    # It should be relatively constant (modulo the global max influence)
    geo_a_results = results[results['geo_code'] == 'GEO_A']
    # We expect some predictions
    assert len(geo_a_results) > 0
    # Last calculated score check
    last_score_a = geo_a_results.iloc[-1]['risk_score_calculated']
    assert last_score_a > 0
    
    # Check Geo B (Increasing)
    geo_b_results = results[results['geo_code'] == 'GEO_B']
    last_score_b = geo_b_results.iloc[-1]['risk_score_calculated']
    
    # Geo B has higher volume AND positive trend, so Score B should be > Score A
    assert last_score_b > last_score_a
    
    print(f"Score A (Stable Low): {last_score_a}")
    print(f"Score B (Increasing High): {last_score_b}")


def test_zero_division_protection():
    """Test robustness against 0 volume or missing previous data"""
    dates = pd.date_range(start="2023-01-01", periods=15, freq="MS")
    data = []
    
    # Geo C: Always 0
    for d in dates:
        data.append({
            "date": d,
            "geo_code": "GEO_C",
            "total_applications": 0
        })
        
    df = pd.DataFrame(data)
    engine = MockEngine()
    
    results = calculate_risk_and_predict(df, engine)
    
    if not results.empty:
        geo_c = results[results['geo_code'] == 'GEO_C']
        if not geo_c.empty:
            assert geo_c.iloc[-1]['risk_score_calculated'] == 0

