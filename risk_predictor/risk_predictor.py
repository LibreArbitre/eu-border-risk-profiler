import os
import time
import schedule
import pandas as pd
import numpy as np
from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy import table, column
from sklearn.ensemble import RandomForestRegressor
from datetime import datetime

# Config
DB_USER = os.getenv('DB_USER', 'user')
DB_PASSWORD = os.getenv('DB_PASSWORD', 'password')
DB_NAME = os.getenv('DB_NAME', 'eubrp_db')
DB_HOST = os.getenv('DB_HOST', 'db')
DB_PORT = os.getenv('DB_PORT', '5432')

DATABASE_URL = f"postgresql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"

def get_db_engine():
    return create_engine(DATABASE_URL)

def get_data_from_db():
    print("Fetching data from DB...", flush=True)
    try:
        engine = get_db_engine()
        # Fetch only NASY_APP (First Time Applicants)
        query = "SELECT date, geo_code, total_applications FROM asylum_data WHERE applicant_type = 'NASY_APP' ORDER BY date"
        df = pd.read_sql(query, engine)
        return df
    except Exception as e:
        print(f"Error reading DB: {e}", flush=True)
        return pd.DataFrame()

def calculate_risk_and_predict(df):
    if df.empty:
        return pd.DataFrame()

    predictions = []

    # Ensure date is datetime
    df['date'] = pd.to_datetime(df['date'])

    print(f"Processing {len(df['geo_code'].unique())} countries...", flush=True)

    for geo, group in df.groupby('geo_code'):
        if len(group) < 12:
            # Need some history for lags
            continue

        group = group.sort_values('date')

        # --- 1. Calculate Risk Score ---
        # Features for Score
        group['prev_total'] = group['total_applications'].shift(1)
        group['variation'] = (group['total_applications'] - group['prev_total']) / (group['prev_total'] + 1) # +1 to avoid div by 0

        max_vol = group['total_applications'].max()
        if max_vol == 0: max_vol = 1
        group['vol_norm'] = group['total_applications'] / max_vol

        # Formula: 40% Volume + 60% Variation (Positive)
        # We assume Variation > 0 increases risk. Variation < 0 decreases it (but we clip at 0 for the formula? or let it reduce score?)
        # Let's use simple weighted sum, but normalize variation to something 0-1ish?
        # Variation can be > 1 (e.g. 200%).
        # Let's cap variation impact.
        # Score = (0.4 * vol_norm + 0.6 * tanh(variation)) * 100?
        # Let's stick to simple: Score = (0.4 * vol_norm + 0.6 * variation) * 100
        # But variation can be negative.
        # Risk score usually 0-100.
        # Let's clip variation at 0.

        group['risk_score'] = (0.4 * group['vol_norm'] + 0.6 * group['variation'].clip(lower=0)) * 100
        group['risk_score'] = group['risk_score'].fillna(0)

        # --- 2. Predict ---
        # Prepare Features
        group['lag_1'] = group['risk_score'].shift(1)
        group['lag_2'] = group['risk_score'].shift(2)
        group['lag_3'] = group['risk_score'].shift(3)
        group['month'] = group['date'].dt.month

        train_df = group.dropna()
        if len(train_df) < 6:
            continue

        X = train_df[['lag_1', 'lag_2', 'lag_3', 'month']]
        y = train_df['risk_score']

        model = RandomForestRegressor(n_estimators=50, random_state=42)
        model.fit(X, y)

        # Predict for M+1, M+2, M+3 from the LAST available point
        last_row = group.iloc[-1]
        last_date = last_row['date']
        current_score = last_row['risk_score']

        # Lags for the first prediction: [Score(t), Score(t-1), Score(t-2)]
        current_lags = [last_row['risk_score'], last_row['lag_1'], last_row['lag_2']]

        # We want to predict t+1.
        # Features for t+1: lag_1=Score(t), lag_2=Score(t-1), lag_3=Score(t-2), month=Month(t+1)

        for i in range(1, 4):
            next_date = last_date + pd.DateOffset(months=i)
            next_month = next_date.month

            # Predict
            features = np.array([current_lags[0], current_lags[1], current_lags[2], next_month]).reshape(1, -1)
            # Handle NaN in features? (Should not happen if last_row is valid)
            if np.isnan(features).any():
                 pred = 0
            else:
                 pred = model.predict(features)[0]

            predictions.append({
                'date': last_date.date(),
                'geo_code': geo,
                'risk_score_calculated': float(current_score),
                'prediction_target_month': next_date.date(),
                'predicted_risk_score': float(pred),
                'model_version': 'v1.0-RF'
            })

            # Shift lags
            # New lags for t+2: [Pred(t+1), Score(t), Score(t-1)]
            current_lags = [pred] + current_lags[:-1]

    return pd.DataFrame(predictions)

def save_predictions(df):
    if df.empty:
        print("No predictions to save.", flush=True)
        return

    engine = get_db_engine()
    print(f"Saving {len(df)} predictions...", flush=True)

    try:
        with engine.connect() as conn:
            trans = conn.begin()
            try:
                # Table abstraction
                risk_table = table('risk_predictions',
                    column('date'),
                    column('geo_code'),
                    column('risk_score_calculated'),
                    column('prediction_target_month'),
                    column('predicted_risk_score'),
                    column('model_version')
                )

                data_to_insert = df.to_dict(orient='records')

                chunk_size = 1000
                for i in range(0, len(data_to_insert), chunk_size):
                    chunk = data_to_insert[i:i+chunk_size]
                    stmt = insert(risk_table).values(chunk)
                    # Upsert
                    stmt = stmt.on_conflict_do_update(
                        index_elements=['geo_code', 'prediction_target_month'],
                        set_={
                            'risk_score_calculated': stmt.excluded.risk_score_calculated,
                            'predicted_risk_score': stmt.excluded.predicted_risk_score,
                            'date': stmt.excluded.date, # Update source date
                            'model_version': stmt.excluded.model_version
                        }
                    )
                    conn.execute(stmt)

                trans.commit()
                print("Predictions saved.", flush=True)
            except Exception as e:
                trans.rollback()
                print(f"Error saving predictions: {e}", flush=True)
    except Exception as e:
        print(f"DB Error: {e}", flush=True)

def run_job():
    print(f"--- Starting Risk Predictor Job at {datetime.now()} ---", flush=True)
    df = get_data_from_db()
    if not df.empty:
        preds = calculate_risk_and_predict(df)
        save_predictions(preds)
    else:
        print("No data found in DB.", flush=True)
    print("--- Job Finished ---", flush=True)

def start_scheduler():
    run_job()
    # Run every day
    schedule.every().day.at("03:00").do(run_job)

    print("Risk Predictor Scheduler started.", flush=True)
    while True:
        schedule.run_pending()
        time.sleep(60)

if __name__ == "__main__":
    print("Risk Predictor Service Starting...", flush=True)
    time.sleep(15) # Wait for Harvester?
    start_scheduler()
