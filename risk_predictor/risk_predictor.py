import argparse
import hashlib
import logging
import os
import pickle
import sys
import time
import uuid
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import schedule
from sklearn.ensemble import RandomForestRegressor
from sqlalchemy import (
    JSON,
    Column,
    DateTime,
    Integer,
    LargeBinary,
    MetaData,
    String,
    Table,
    create_engine,
    select,
    text,
)
from sqlalchemy.dialects.postgresql import insert

# Config
DB_USER = os.getenv("DB_USER", "user")
DB_PASSWORD = os.getenv("DB_PASSWORD", "password")
DB_NAME = os.getenv("DB_NAME", "eubrp_db")
DB_HOST = os.getenv("DB_HOST", "db")
DB_PORT = os.getenv("DB_PORT", "5432")

RETRY_MAX_ATTEMPTS = int(os.getenv("RETRY_MAX_ATTEMPTS", "3"))
RETRY_BACKOFF_SECONDS = float(os.getenv("RETRY_BACKOFF_SECONDS", "2"))
EXIT_ON_FAILURE = os.getenv("EXIT_ON_FAILURE", "true").lower() == "true"
HEALTH_FILE = os.getenv("PREDICTOR_HEALTH_FILE", "/tmp/predictor_health")
PREDICTION_RETENTION_DAYS = int(os.getenv("PREDICTION_RETENTION_DAYS", "90"))
# A run that sees only data older than this many days is considered to be
# reading a stale snapshot of asylum_data (e.g. because the harvester is
# still mid-swap). The predictor will keep waiting instead of computing
# and persisting predictions that the daily schedule won't refresh until
# the next cycle. Eurostat publishes monthly with a typical 1-2 month lag,
# so 120 days leaves headroom while still catching real freshness issues.
DATA_FRESHNESS_MAX_AGE_DAYS = int(os.getenv("DATA_FRESHNESS_MAX_AGE_DAYS", "120"))

DATABASE_URL = os.getenv(
    "DATABASE_URL", f"postgresql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
)

MODEL_NAME = "random_forest_risk"
MODEL_HYPERPARAMS = {"n_estimators": 50, "random_state": 42}
MODEL_MAX_AGE_DAYS = int(os.getenv("MODEL_MAX_AGE_DAYS", "30"))
DRIFT_TOLERANCE = float(os.getenv("DRIFT_TOLERANCE", "0.15"))
# Fraction of the most recent observations held out for honest evaluation. The
# rest is used to fit the candidate model whose error on the hold-out becomes
# the reported `test_mae`. The production model is then refit on the full
# dataset so we don't waste signal at inference time.
HOLDOUT_TEST_RATIO = float(os.getenv("HOLDOUT_TEST_RATIO", "0.2"))
HOLDOUT_MIN_TEST = int(os.getenv("HOLDOUT_MIN_TEST", "2"))
HOLDOUT_MIN_TRAIN = int(os.getenv("HOLDOUT_MIN_TRAIN", "6"))

# Define SQLAlchemy table for model registry
metadata = MetaData()
model_registry_table = Table(
    "model_registry",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("model_name", String(100), nullable=False),
    Column("geo_code", String(10), nullable=False),
    Column("model_version", String(50), nullable=False),
    Column("trained_at", DateTime, nullable=False),
    Column("hyperparameters", JSON),
    Column("model_artifact", LargeBinary, nullable=False),
)


def get_db_engine():
    return create_engine(DATABASE_URL)


def configure_logging():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
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
    # Aggregate all citizenships per destination country (geo_code)
    # This sums total_applications across all citizen_codes for each geo_code and date
    query = """
        SELECT date, geo_code, SUM(total_applications) as total_applications 
        FROM asylum_data 
        WHERE applicant_type = 'FRST' 
        GROUP BY date, geo_code 
        ORDER BY date
    """
    df = pd.read_sql(query, engine)
    logging.info(f"Loaded {len(df)} aggregated rows for {df['geo_code'].nunique()} countries")
    return df


def load_latest_model(engine, geo_code):
    try:
        with engine.connect() as conn:
            result = conn.execute(
                select(
                    model_registry_table.c.id,
                    model_registry_table.c.model_artifact,
                    model_registry_table.c.trained_at,
                    model_registry_table.c.hyperparameters,
                )
                .where(
                    (model_registry_table.c.model_name == MODEL_NAME) & (model_registry_table.c.geo_code == geo_code)
                )
                .order_by(model_registry_table.c.trained_at.desc())
                .limit(1)
            ).fetchone()

            if result:
                metadata = result.hyperparameters or {}
                trained_at = result.trained_at
                return pickle.loads(result.model_artifact), result.id, trained_at, metadata
    except Exception as e:
        print(f"Error loading persisted model for {geo_code}: {e}", flush=True)

    return None, None, None, {}


def persist_model(engine, geo_code, model, metadata=None):
    try:
        payload = {
            "model_name": MODEL_NAME,
            "geo_code": geo_code,
            "model_version": datetime.utcnow().strftime("v%Y%m%d%H%M%S"),
            "trained_at": datetime.utcnow(),
            "hyperparameters": metadata or MODEL_HYPERPARAMS,
            "model_artifact": pickle.dumps(model),
        }

        with engine.begin() as conn:
            result = conn.execute(insert(model_registry_table).returning(model_registry_table.c.id), [payload])
            model_id = result.scalar()
            print(f"Persisted new model for {geo_code} with id {model_id}", flush=True)
            return model_id
    except Exception as e:
        print(f"Error persisting model for {geo_code}: {e}", flush=True)
        return None


def train_model(train_df):
    model = RandomForestRegressor(**MODEL_HYPERPARAMS)
    model.fit(train_df[["lag_1", "lag_2", "lag_3", "month"]], train_df["risk_score"])
    return model


def compute_data_signature(train_df: pd.DataFrame) -> str:
    signature_df = train_df[["date", "total_applications"]].copy()
    signature_df["date"] = pd.to_datetime(signature_df["date"])
    signature_df = signature_df.sort_values("date")
    payload = signature_df.to_json(date_format="iso", orient="records")
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def model_is_stale(trained_at: datetime | None) -> bool:
    if trained_at is None:
        return True
    return datetime.utcnow() - trained_at > timedelta(days=MODEL_MAX_AGE_DAYS)


def evaluate_model(train_df: pd.DataFrame, model) -> float | None:
    """In-sample MAE for a trained model.

    Kept for backward compatibility with existing tests/callers; this number
    is the residual error on the data the model was fit on, so it cannot be
    used as a generalization signal. Prefer ``evaluate_model_holdout`` when
    you need an honest performance estimate.
    """
    if model is None:
        return None
    try:
        features = train_df[["lag_1", "lag_2", "lag_3", "month"]]
        target = train_df["risk_score"]
        preds = model.predict(features)
        return float(np.mean(np.abs(preds - target)))
    except Exception:
        logging.exception("Failed to evaluate model performance")
        return None


def predict_with_quantiles(model, features: np.ndarray, quantiles=(0.1, 0.9)):
    """Return ``(point_estimate, low_quantile, high_quantile)`` for a single sample.

    ``RandomForestRegressor.predict`` averages every tree's output. Here we
    keep the per-tree predictions instead and report the requested quantiles
    plus the mean (for backwards compatibility with the existing
    ``predicted_risk_score`` field). This gives a free uncertainty band
    without adding a dependency.
    """
    if model is None:
        return None, None, None
    try:
        per_tree = np.array(
            [estimator.predict(features)[0] for estimator in getattr(model, "estimators_", [])]
        )
    except Exception:
        logging.exception("Failed to extract per-tree predictions; falling back to mean only")
        try:
            mean = float(model.predict(features)[0])
            return mean, None, None
        except Exception:
            return None, None, None

    if per_tree.size == 0:
        # Fallback for models that don't expose estimators_ (shouldn't happen
        # with sklearn RF, but stay defensive).
        try:
            mean = float(model.predict(features)[0])
            return mean, None, None
        except Exception:
            return None, None, None

    point = float(per_tree.mean())
    low_q, high_q = quantiles
    p_low = float(np.quantile(per_tree, low_q))
    p_high = float(np.quantile(per_tree, high_q))
    return point, p_low, p_high


def temporal_split(train_df: pd.DataFrame, test_ratio: float = HOLDOUT_TEST_RATIO,
                   min_test: int = HOLDOUT_MIN_TEST, min_train: int = HOLDOUT_MIN_TRAIN):
    """Split a per-country frame into (train, test) chronologically.

    Returns ``(train_part, test_part)`` where ``test_part`` is the most
    recent ``test_ratio`` fraction of rows (capped to leave at least
    ``min_train`` rows for fitting). Returns ``(train_df, None)`` if the
    series is too short to support a meaningful hold-out — callers should
    skip honest evaluation in that case.
    """
    if train_df is None or len(train_df) == 0:
        return train_df, None

    ordered = train_df.sort_values("date") if "date" in train_df.columns else train_df

    n = len(ordered)
    n_test = max(min_test, int(round(n * test_ratio)))
    n_test = min(n_test, n - min_train)
    if n_test < min_test:
        return ordered, None

    train_part = ordered.iloc[:-n_test]
    test_part = ordered.iloc[-n_test:]
    return train_part, test_part


def evaluate_model_holdout(test_df: pd.DataFrame, model) -> float | None:
    """MAE on a hold-out frame the model has *not* seen.

    Returns ``None`` if the test frame is empty/None or evaluation fails.
    """
    if model is None or test_df is None or len(test_df) == 0:
        return None
    try:
        features = test_df[["lag_1", "lag_2", "lag_3", "month"]]
        target = test_df["risk_score"]
        preds = model.predict(features)
        return float(np.mean(np.abs(preds - target)))
    except Exception:
        logging.exception("Failed to evaluate model on hold-out")
        return None


def log_model_drift(old_mae: float | None, new_mae: float | None, geo_code: str):
    if old_mae is None or new_mae is None:
        return

    delta = new_mae - old_mae
    pct_change = delta / old_mae if old_mae else float("inf")
    logging.info(
        "Model performance for %s. Prev MAE=%.4f, New MAE=%.4f, Δ=%.4f (%.2f%%)",
        geo_code,
        old_mae,
        new_mae,
        delta,
        pct_change * 100,
    )

    if pct_change > DRIFT_TOLERANCE:
        logging.warning(
            "Potential performance drift detected for %s (MAE worsened by %.2f%%)",
            geo_code,
            pct_change * 100,
        )


def get_or_train_model(
    engine,
    geo_code,
    train_df,
    loader=load_latest_model,
    persister=persist_model,
):
    data_signature = compute_data_signature(train_df)
    model, model_id, trained_at, metadata = loader(engine, geo_code)

    existing_signature = metadata.get("data_signature") if metadata else None
    stale = model_is_stale(trained_at)

    if model and model_id and existing_signature == data_signature and not stale:
        logging.info(
            "Reusing cached model %s for %s (signature=%s)",
            model_id,
            geo_code,
            data_signature[:8],
        )
        return model, model_id, {"reused": True, "data_signature": data_signature}

    train_part, test_part = temporal_split(train_df)
    has_holdout = test_part is not None and len(test_part) > 0

    # Honest hold-out evaluation: previous model's MAE on data it has never
    # seen, vs. a candidate model fit on the train portion only and scored
    # on the same hold-out. This gives us a real generalization signal for
    # drift detection.
    old_test_mae = evaluate_model_holdout(test_part, model) if (model and has_holdout) else None
    candidate_test_mae = None
    if has_holdout:
        candidate = train_model(train_part)
        candidate_test_mae = evaluate_model_holdout(test_part, candidate)

    # The deployed model is fit on the FULL training set so we don't waste
    # the most recent signal at inference time.
    model = train_model(train_df)
    new_mae = evaluate_model(train_df, model)  # in-sample residual
    log_model_drift(old_test_mae, candidate_test_mae, geo_code)

    metadata_payload = {
        **MODEL_HYPERPARAMS,
        "data_signature": data_signature,
        "train_size": len(train_df),
    }
    if new_mae is not None:
        metadata_payload["train_mae"] = new_mae
    if candidate_test_mae is not None:
        metadata_payload["test_mae"] = candidate_test_mae
        metadata_payload["test_size"] = len(test_part)
    if old_test_mae is not None:
        metadata_payload["prev_test_mae"] = old_test_mae
    model_id = persister(engine, geo_code, model, metadata_payload)

    if model_id is None:
        raise RuntimeError(f"Failed to persist model for {geo_code}")

    logging.info(
        "Trained and persisted model %s for %s (signature=%s, stale=%s)",
        model_id,
        geo_code,
        data_signature[:8],
        stale,
    )

    return model, model_id, {
        "reused": False,
        "data_signature": data_signature,
        "train_mae": new_mae,
        "test_mae": candidate_test_mae,
    }


def calculate_risk_and_predict(df, engine):
    if df.empty:
        return pd.DataFrame()

    predictions = []

    # Ensure date is datetime
    df["date"] = pd.to_datetime(df["date"])

    # Calculate Global Max Volume for normalization (User Request: Global consistency)
    global_max_vol = df["total_applications"].max()
    if global_max_vol == 0:
        global_max_vol = 1
    # Logarithmic Scale for Global Max (to handle 2015 crisis outlier)
    global_max_log = np.log1p(global_max_vol)
    logging.info("Global Max Volume: %s (Log1p: %s)", global_max_vol, global_max_log)

    for geo, group in df.groupby("geo_code"):
        if len(group) < 12:
            # Need some history for lags
            continue

        group = group.sort_values("date")

        # --- 0. Data Cleaning (Handle Data Lag) ---
        # If the last month is 0 but previous month was significant, it's likely missing data (not real 0).
        # Eurostat often publishes the column for the new month before all countries report.
        if not group.empty:
            last_val = group["total_applications"].iloc[-1]
            prev_val = group["total_applications"].iloc[-2] if len(group) > 1 else 0

            if last_val == 0 and prev_val > 100:
                logging.info(f"Dropping last month for {geo} (Likely missing data: {prev_val} -> {last_val})")
                group = group.iloc[:-1]

        # --- 1. Calculate Risk Score ---
        # Features for Score
        # Variation calculation
        group["prev_total"] = group["total_applications"].shift(1)
        group["variation"] = (group["total_applications"] - group["prev_total"]) / (group["prev_total"].replace(0, 1))

        # Normalize volume (0 to 1) against GLOBAL MAX using LOG SCALE
        # This prevents the 2015 crisis (1.3M) from crushing all current scores to 0.
        # Spain (128k) -> ~0.85, DE (27k) -> ~0.72, EL (4k) -> ~0.59
        group["vol_norm"] = np.log1p(group["total_applications"]) / global_max_log

        # Formula: Multiplicative approach (Volume * Trend)
        # Base score is the normalized volume (0-100 equivalent)
        # We modulate it by the trend : * (1 + variation)

        group["risk_score"] = group["vol_norm"] * (1 + group["variation"]) * 100

        # Cap at 100 and floor at 0
        group["risk_score"] = group["risk_score"].clip(lower=0, upper=100)
        group["risk_score"] = group["risk_score"].fillna(0)

        # --- 2. Predict ---
        # Prepare Features
        group["lag_1"] = group["risk_score"].shift(1)
        group["lag_2"] = group["risk_score"].shift(2)
        group["lag_3"] = group["risk_score"].shift(3)
        group["month"] = group["date"].dt.month

        train_df = group.dropna()
        if len(train_df) < 6:
            continue

        model, model_id, model_info = get_or_train_model(engine, geo, train_df)
        if model_info.get("reused"):
            logging.info(
                "Model %s for %s reused (signature=%s)",
                model_id,
                geo,
                model_info.get("data_signature", ""),
            )
        else:
            logging.info(
                "Model %s for %s retrained (signature=%s, train_mae=%s, test_mae=%s)",
                model_id,
                geo,
                model_info.get("data_signature", ""),
                model_info.get("train_mae"),
                model_info.get("test_mae"),
            )

        # Predict for M+1, M+2, M+3 from the LAST available point
        last_row = group.iloc[-1]
        last_date = last_row["date"]
        current_score = last_row["risk_score"]

        # Lags for the first prediction: [Score(t), Score(t-1), Score(t-2)]
        current_lags = [last_row["risk_score"], last_row["lag_1"], last_row["lag_2"]]

        # We want to predict t+1.
        # Features for t+1: lag_1=Score(t), lag_2=Score(t-1), lag_3=Score(t-2), month=Month(t+1)

        for i in range(1, 4):
            next_date = last_date + pd.DateOffset(months=i)
            next_month = next_date.month

            # Predict — pull per-tree predictions so we can report a P10/P90
            # band alongside the point estimate. The point estimate is the
            # mean across trees, which matches sklearn's default predict().
            features = np.array([current_lags[0], current_lags[1], current_lags[2], next_month]).reshape(1, -1)
            if np.isnan(features).any():
                pred, p10, p90 = 0.0, None, None
            else:
                pred, p10, p90 = predict_with_quantiles(model, features)
                if pred is None:
                    pred, p10, p90 = 0.0, None, None

            # Cap predictions at 100 and floor at 0 for the score scale.
            pred = max(0.0, min(100.0, pred))
            if p10 is not None:
                p10 = max(0.0, min(100.0, p10))
            if p90 is not None:
                p90 = max(0.0, min(100.0, p90))

            predictions.append(
                {
                    "date": last_date.date(),
                    "geo_code": geo,
                    "risk_score_calculated": float(current_score),
                    "prediction_target_month": next_date.date(),
                    "predicted_risk_score": float(pred),
                    "predicted_risk_score_p10": float(p10) if p10 is not None else None,
                    "predicted_risk_score_p90": float(p90) if p90 is not None else None,
                    "model_id": model_id,
                }
            )

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
        with open(HEALTH_FILE, "w", encoding="utf-8") as f:
            f.write(str(payload))
    except Exception:
        logging.exception("Failed to write health status")


def check_health():
    try:
        with open(HEALTH_FILE, "r", encoding="utf-8") as f:
            data = f.read()
            if "healthy" in data:
                return True
    except FileNotFoundError:
        logging.error("Health file not found at %s", HEALTH_FILE)
    except Exception:
        logging.exception("Error reading health file")
    return False


@retry("DB save")
def _build_run_metadata(run_metadata=None):
    if run_metadata:
        return {
            "run_id": run_metadata.get("run_id", str(uuid.uuid4())),
            "prediction_date": run_metadata.get("prediction_date", datetime.utcnow()),
        }

    return {"run_id": str(uuid.uuid4()), "prediction_date": datetime.utcnow()}


def purge_old_predictions(engine, retention_days: int):
    if retention_days <= 0:
        return

    cutoff_date = datetime.utcnow() - timedelta(days=retention_days)
    with engine.begin() as conn:
        result = conn.execute(
            text("DELETE FROM risk_predictions WHERE prediction_date < :cutoff"),
            {"cutoff": cutoff_date},
        )
        logging.info("Purged %s old prediction rows", result.rowcount)


def save_predictions(df, engine=None, run_metadata=None):
    if df.empty:
        logging.info("No predictions to save.")
        return

    engine = engine or get_db_engine()
    logging.info("Saving %s predictions...", len(df))

    metadata = _build_run_metadata(run_metadata)

    try:
        predictions_df = pd.DataFrame(df.to_dict(orient="records"))
        predictions_df["run_id"] = metadata["run_id"]
        predictions_df["prediction_date"] = metadata["prediction_date"]

        predictions_df.to_sql(
            "risk_predictions",
            engine,
            if_exists="append",
            index=False,
            method="multi",
            chunksize=500,
        )
        logging.info(
            "Predictions saved for run %s at %s.",
            metadata["run_id"],
            metadata["prediction_date"],
        )

        purge_old_predictions(engine, PREDICTION_RETENTION_DAYS)
    except Exception as e:
        logging.exception("Error saving predictions")
        raise e


def _is_data_fresh(df) -> bool:
    """Return True if asylum_data contains at least one row newer than the
    DATA_FRESHNESS_MAX_AGE_DAYS cutoff.

    Treating an empty frame OR a frame whose newest `date` is months behind
    the wall clock as "not fresh" prevents the predictor from racing the
    harvester at boot and saving predictions against a stale snapshot.
    """
    if df is None or df.empty or "date" not in df.columns:
        return False
    try:
        max_date = pd.to_datetime(df["date"]).max()
    except Exception:
        logging.exception("Failed to parse data dates while checking freshness")
        return False
    cutoff = pd.Timestamp.utcnow().tz_localize(None) - pd.Timedelta(days=DATA_FRESHNESS_MAX_AGE_DAYS)
    return max_date >= cutoff


def run_job():
    logging.info("--- Starting Risk Predictor Job ---")
    success = True
    message = ""
    try:
        engine = get_db_engine()

        # Wait for FRESH data loop. We don't just check that asylum_data has
        # rows — a previous successful harvest can leave months-old data
        # behind. Keep polling until a row newer than DATA_FRESHNESS_MAX_AGE_DAYS
        # appears, which is the harvester's signal that its swap committed.
        max_wait_attempts = 60  # Wait up to 1 hour (60 * 60s)
        df = pd.DataFrame()
        for attempt in range(max_wait_attempts):
            df = get_data_from_db()
            if _is_data_fresh(df):
                break
            if df.empty:
                logging.warning(
                    f"asylum_data empty (attempt {attempt + 1}/{max_wait_attempts}). Waiting 60s..."
                )
            else:
                latest = pd.to_datetime(df["date"]).max().date()
                logging.warning(
                    "asylum_data only has data up to %s, older than %s days "
                    "(attempt %s/%s). Waiting 60s for harvester to refresh...",
                    latest,
                    DATA_FRESHNESS_MAX_AGE_DAYS,
                    attempt + 1,
                    max_wait_attempts,
                )
            time.sleep(60)

        if not _is_data_fresh(df):
            if df.empty:
                raise ValueError(
                    "No data found in DB after waiting. Harvester might be broken."
                )
            latest = pd.to_datetime(df["date"]).max().date()
            raise ValueError(
                f"asylum_data only has data up to {latest}, older than "
                f"{DATA_FRESHNESS_MAX_AGE_DAYS} days. Refusing to run on stale snapshot."
            )

        preds = calculate_risk_and_predict(df, engine)
        save_predictions(preds, engine=engine)
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


def ensure_predictions_schema(engine=None) -> None:
    """Apply idempotent schema migrations for ``risk_predictions``.

    PostgreSQL's docker-entrypoint only runs ``/docker-entrypoint-initdb.d``
    scripts on the *first* volume initialisation. On a managed deployment
    (Dokploy, Coolify, etc.) the database volume usually predates the
    schema changes shipped with newer code, so we apply the column-level
    additions defensively at predictor startup. ``ADD COLUMN IF NOT EXISTS``
    is a no-op when the columns are already present, so the cost on a
    healthy deployment is a single ALTER round-trip per process start.
    """
    engine = engine or get_db_engine()
    statements = [
        "ALTER TABLE risk_predictions "
        "ADD COLUMN IF NOT EXISTS predicted_risk_score_p10 NUMERIC(5, 2)",
        "ALTER TABLE risk_predictions "
        "ADD COLUMN IF NOT EXISTS predicted_risk_score_p90 NUMERIC(5, 2)",
    ]
    try:
        with engine.begin() as conn:
            for stmt in statements:
                conn.execute(text(stmt))
        logging.info("Schema migrations applied (or already up-to-date).")
    except Exception:
        # Don't crash the predictor here — surface the failure but let the
        # subsequent INSERT raise its own, more contextual error if the
        # missing column genuinely persists.
        logging.exception("Failed to apply schema migrations; continuing")


def start_scheduler():
    ensure_predictions_schema()
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
    time.sleep(15)  # Wait for Harvester?
    start_scheduler()
