import argparse
import logging
import os
import pickle
import sys
import time
import schedule
import pandas as pd
import numpy as np
from sqlalchemy import (
    JSON,
    Column,
    DateTime,
    Integer,
    LargeBinary,
    MetaData,
    Table,
    String,
    create_engine,
    select,
    table,
    column,
)
from sqlalchemy.dialects.postgresql import insert
from sklearn.ensemble import RandomForestRegressor
from datetime import datetime

# Config
DB_USER = os.getenv('DB_USER', 'user')
DB_PASSWORD = os.getenv('DB_PASSWORD', 'password')
DB_NAME = os.getenv('DB_NAME', 'eubrp_db')
DB_HOST = os.getenv('DB_HOST', 'db')
DB_PORT = os.getenv('DB_PORT', '5432')

RETRY_MAX_ATTEMPTS = int(os.getenv('RETRY_MAX_ATTEMPTS', '3'))
RETRY_BACKOFF_SECONDS = float(os.getenv('RETRY_BACKOFF_SECONDS', '2'))
EXIT_ON_FAILURE = os.getenv('EXIT_ON_FAILURE', 'true').lower() == 'true'
HEALTH_FILE = os.getenv('PREDICTOR_HEALTH_FILE', '/tmp/predictor_health')

DATABASE_URL = f"postgresql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"

MODEL_NAME = "random_forest_risk"
MODEL_HYPERPARAMS = {"n_estimators": 50, "random_state": 42}

# Define SQLAlchemy table for model registry
metadata = MetaData()
model_registry_table = Table(
    'model_registry',
    metadata,
    Column('id', Integer, primary_key=True),
    Column('model_name', String(100), nullable=False),
    Column('geo_code', String(10), nullable=False),
    Column('model_version', String(50), nullable=False),
    Column('trained_at', DateTime, nullable=False),
    Column('hyperparameters', JSON),
    Column('model_artifact', LargeBinary, nullable=False)
)

def get_db_engine():
    return create_engine(DATABASE_URL)

def configure_logging():
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(message)s',
    )


def retry(operation_name):
    def decorator(func):
        def wrapper(*args, **kwargs):
            delay = RETRY_BACKOFF_SECONDS
            for attempt in range(1, RETRY_MAX_ATTEMPTS + 1):
                try:
                    return func(*args, **kwargs)
                except Exception as exc:  # noqa: PERF203 acceptable for logging context
                    logging.warning(
                        "%s failed on attempt %s/%s: %s",
                        operation_name,
                        attempt,
                        RETRY_MAX_ATTEMPTS,
                        exc,
                    )
                    if attempt == RETRY_MAX_ATTEMPTS:
                        raise
                    time.sleep(delay)
                    delay *= 2
        return wrapper
    return decorator


@retry("DB read")
def get_data_from_db():
    logging.info("Fetching data from DB...")
    engine = get_db_engine()
    # Fetch only NASY_APP (First Time Applicants)
    query = "SELECT date, geo_code, total_applications FROM asylum_data WHERE applicant_type = 'FRST' ORDER BY date"
    df = pd.read_sql(query, engine)
    return df

def load_latest_model(engine, geo_code):
    try:
        with engine.connect() as conn:
            result = conn.execute(
                select(
                    model_registry_table.c.id,
                    model_registry_table.c.model_artifact
                )
                .where(
                    (model_registry_table.c.model_name == MODEL_NAME)
                    & (model_registry_table.c.geo_code == geo_code)
                )
                .order_by(model_registry_table.c.trained_at.desc())
                .limit(1)
            ).fetchone()

            if result:
                return pickle.loads(result.model_artifact), result.id
    except Exception as e:
        print(f"Error loading persisted model for {geo_code}: {e}", flush=True)

    return None, None


def persist_model(engine, geo_code, model):
    try:
        payload = {
            'model_name': MODEL_NAME,
            'geo_code': geo_code,
            'model_version': datetime.utcnow().strftime("v%Y%m%d%H%M%S"),
            'trained_at': datetime.utcnow(),
            'hyperparameters': MODEL_HYPERPARAMS,
            'model_artifact': pickle.dumps(model)
        }

        with engine.begin() as conn:
            result = conn.execute(
                insert(model_registry_table)
                .returning(model_registry_table.c.id),
                [payload]
            )
            model_id = result.scalar()
            print(f"Persisted new model for {geo_code} with id {model_id}", flush=True)
            return model_id
    except Exception as e:
        print(f"Error persisting model for {geo_code}: {e}", flush=True)
        return None


def train_model(train_df):
    model = RandomForestRegressor(**MODEL_HYPERPARAMS)
    model.fit(train_df[['lag_1', 'lag_2', 'lag_3', 'month']], train_df['risk_score'])
    return model


def get_or_train_model(engine, geo_code, train_df):
    model, model_id = load_latest_model(engine, geo_code)

    if model and model_id:
        print(f"Loaded persisted model {model_id} for {geo_code}", flush=True)
        return model, model_id

    model = train_model(train_df)
    model_id = persist_model(engine, geo_code, model)

    if model_id is None:
        raise RuntimeError(f"Failed to persist model for {geo_code}")

    return model, model_id


def calculate_risk_and_predict(df, engine):
    if df.empty:
        return pd.DataFrame()

    predictions = []

    # Ensure date is datetime
    df['date'] = pd.to_datetime(df['date'])

    logging.info("Processing %s countries...", len(df['geo_code'].unique()))

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

        model, model_id = get_or_train_model(engine, geo, train_df)

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
                'model_id': model_id
            })

            # Shift lags
            # New lags for t+2: [Pred(t+1), Score(t), Score(t-1)]
            current_lags = [pred] + current_lags[:-1]

    return pd.DataFrame(predictions)


def write_health(status: bool, message: str = ""):
    payload = {
        "status": "healthy" if status else "unhealthy",
        "timestamp": datetime.utcnow().isoformat(),
        "message": message,
    }
    try:
        with open(HEALTH_FILE, 'w', encoding='utf-8') as f:
            f.write(str(payload))
    except Exception:
        logging.exception("Failed to write health status")


def check_health():
    try:
        with open(HEALTH_FILE, 'r', encoding='utf-8') as f:
            data = f.read()
            if 'healthy' in data:
                return True
    except FileNotFoundError:
        logging.error("Health file not found at %s", HEALTH_FILE)
    except Exception:
        logging.exception("Error reading health file")
    return False


@retry("DB save")
def save_predictions(df):
    if df.empty:
        logging.info("No predictions to save.")
        return

    engine = get_db_engine()
    logging.info("Saving %s predictions...", len(df))

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
                    column('model_id')
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
                            'model_id': stmt.excluded.model_id
                        }
                    )
                    conn.execute(stmt)

                trans.commit()
                logging.info("Predictions saved.")
            except Exception as e:
                trans.rollback()
                logging.exception("Error saving predictions")
                raise e
    except Exception as e:
        logging.exception("DB Error")
        raise e


def run_job():
    logging.info("--- Starting Risk Predictor Job ---")
    success = True
    message = ""
    try:
        engine = get_db_engine()
        df = get_data_from_db()
        if df.empty:
            raise ValueError("No data found in DB.")
        preds = calculate_risk_and_predict(df, engine)
        save_predictions(preds)
    except Exception as exc:  # noqa: PERF203 logging
        success = False
        message = str(exc)
        logging.exception("Risk predictor job failed")
        if EXIT_ON_FAILURE:
            write_health(False, message)
            sys.exit(1)
    finally:
        write_health(success, message)
    logging.info("--- Job Finished ---")


def start_scheduler():
    run_job()
    # Run every day
    schedule.every().day.at("03:00").do(run_job)

    logging.info("Risk Predictor Scheduler started.")
    while True:
        schedule.run_pending()
        time.sleep(60)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Risk predictor service")
    parser.add_argument("--healthcheck", action="store_true", help="Run healthcheck and exit")
    args = parser.parse_args()

    configure_logging()

    if args.healthcheck:
        healthy = check_health()
        sys.exit(0 if healthy else 1)

    logging.info("Risk Predictor Service Starting...")
    time.sleep(15) # Wait for Harvester?
    start_scheduler()
