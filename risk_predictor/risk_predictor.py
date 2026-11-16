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
# How many trained model artifacts to keep per (model_name, geo_code) in the
# registry. Retrains INSERT a new pickle every time; without a cap the table
# grows without bound (27 models per monthly run). Models referenced by
# retained predictions are always kept, whatever this value. 0 disables.
MODEL_REGISTRY_KEEP_LAST = int(os.getenv("MODEL_REGISTRY_KEEP_LAST", "6"))
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

# The model predicts the month-over-month CHANGE of the score, not its level
# (see FEATURES / TARGET below). The name differs from the earlier level
# model so its artifacts, which expect other features, are never loaded.
MODEL_NAME = "random_forest_risk_delta"
MODEL_HYPERPARAMS = {"n_estimators": 50, "random_state": 42, "min_samples_leaf": 5}

# Model inputs and output. The smoothed score is highly persistent, and a
# forest trained on its level cannot extrapolate and loses to "same as last
# month". Trained on the change, it adds a small but real edge over that
# naive baseline, which is logged and stored with every retrain.
FEATURES = ["lag_1", "delta_1", "month"]
TARGET = "delta"

# --- Score definition -------------------------------------------------------
# Bump when the formula or its constants change: the version is part of the
# model cache signature, so every cached model is retrained.
SCORE_VERSION = "2"
# Applications are averaged over this many months before anything else. A
# single month is dominated by noise for small Member States and by late
# reporting for all of them.
SMOOTHING_MONTHS = 3
# The trend compares the smoothed volume with the one SMOOTHING_MONTHS
# earlier, is clipped to +/- TREND_CLIP, and moves the score by at most
# TREND_WEIGHT * TREND_CLIP (25%) either way.
TREND_CLIP = 0.5
TREND_WEIGHT = 0.5

# Resident population on 1 January 2026, Eurostat table tps00001 (extracted
# 2026-11-16). Used to express pressure per 100,000 inhabitants. Population
# moves by a few percent a decade, so one reference year is applied to the
# whole history; refresh the table when a new year is published.
POPULATION = {
    "AT": 9215956, "BE": 11955308, "BG": 6423207, "CY": 996571, "CZ": 10915839,
    "DE": 83467117, "DK": 6025603, "EE": 1360745, "EL": 10366586, "ES": 49590099,
    "FI": 5652881, "FR": 69112309, "HR": 3876002, "HU": 9488428, "IE": 5510565,
    "IT": 58942828, "LT": 2887592, "LU": 690959, "LV": 1845096, "MT": 588254,
    "NL": 18130208, "PL": 36332765, "PT": 11424031, "RO": 19041322, "SE": 10605529,
    "SI": 2135107, "SK": 5409407,
}
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


# Memoised: get_data_from_db runs inside the fresh-data wait loop (up to 60
# iterations) and used to build a new Engine, and thus new pooled
# connections, on every call. One Engine per process reuses the pool.
_ENGINE = None


def get_db_engine():
    global _ENGINE
    if _ENGINE is None:
        _ENGINE = create_engine(DATABASE_URL)
    return _ENGINE


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
    # Use the pre-aggregated TOTAL rows produced by the harvester rather
    # than summing per-nationality rows on the fly. The harvester writes
    # one TOTAL row per (date, geo_code) alongside per-nationality rows;
    # filtering on `citizen_code = 'TOTAL'` gives us the country-level
    # series the predictor was always meant to consume, without
    # double-counting the per-nationality breakdown.
    query = """
        SELECT date, geo_code, total_applications
        FROM asylum_data
        WHERE applicant_type = 'FRST'
          AND citizen_code = 'TOTAL'
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
    """Fit the forest on plain arrays so inference never trips sklearn's
    feature-name checks (per-tree prediction passes arrays too)."""
    model = RandomForestRegressor(**MODEL_HYPERPARAMS)
    model.fit(train_df[FEATURES].to_numpy(dtype=float), train_df[TARGET].to_numpy(dtype=float))
    return model


def compute_rate_frame(group: pd.DataFrame, population: float) -> pd.DataFrame:
    """Monthly pressure indicators for one Member State.

    Returns one row per calendar month between the first and last published
    month, with ``total_applications`` (NaN where nothing was published),
    ``rate_per_100k`` (smoothed applications per 100,000 inhabitants) and
    ``trend`` (relative change of the smoothed volume over
    ``SMOOTHING_MONTHS``, clipped to +/- ``TREND_CLIP``).

    Pure function, covered by unit tests.
    """
    series = group.sort_values("date").set_index("date")["total_applications"].astype(float)
    series = series[~series.index.duplicated(keep="last")].asfreq("MS")

    # Reporting lag: a trailing 0 right after a substantial month is a
    # country that has not filed yet, not a collapse.
    if len(series) >= 2 and series.iloc[-1] == 0 and series.iloc[-2] > 100:
        series = series.iloc[:-1]

    smoothed = series.rolling(SMOOTHING_MONTHS, min_periods=SMOOTHING_MONTHS).mean()
    previous = smoothed.shift(SMOOTHING_MONTHS)
    relative_change = smoothed / previous.where(previous > 0) - 1
    # Rising from nothing has no ratio: count it as the maximum rise.
    relative_change = relative_change.where(previous != 0, np.where(smoothed > 0, TREND_CLIP, 0.0))
    trend = relative_change.clip(-TREND_CLIP, TREND_CLIP).fillna(0.0)

    frame = pd.DataFrame(
        {
            "total_applications": series,
            "rate_per_100k": smoothed / population * 100_000,
            "trend": trend,
        }
    )
    return frame.rename_axis("date").reset_index()


def add_score(frame: pd.DataFrame, reference_log: float) -> pd.DataFrame:
    """Add the 0-100 ``risk_score`` to a frame built by ``compute_rate_frame``.

    The rate is log-scaled against the highest rate ever observed in the EU
    (``reference_log``), so one exceptional episode does not flatten every
    other value, then modulated by the trend.
    """
    frame = frame.copy()
    level = np.log1p(frame["rate_per_100k"]) / reference_log
    frame["risk_score"] = (level * (1 + TREND_WEIGHT * frame["trend"]) * 100).clip(lower=0, upper=100)
    return frame


def compute_data_signature(train_df: pd.DataFrame, context: str | None = None) -> str:
    """Hash the country's series plus any cross-country training context.

    ``context`` captures inputs that shape the training target but live
    outside the country's own rows: the risk_score target is normalised
    against the EU-wide maximum volume, so a new all-time peak anywhere
    must invalidate every country's cached model, not just the peak
    country's. Hashing only (date, total_applications) would silently
    reuse models trained against the old scale.
    """
    signature_df = train_df[["date", "total_applications"]].copy()
    signature_df["date"] = pd.to_datetime(signature_df["date"])
    signature_df = signature_df.sort_values("date")
    payload = signature_df.to_json(date_format="iso", orient="records")
    if context:
        payload = f"{payload}|{context}"
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
        preds = model.predict(train_df[FEATURES].to_numpy(dtype=float))
        return float(np.mean(np.abs(preds - train_df[TARGET].to_numpy(dtype=float))))
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

    The model predicts the change of the score; since the forecast is
    ``previous score + predicted change``, the error on the change equals
    the error on the score itself, in score points.

    Returns ``None`` if the test frame is empty/None or evaluation fails.
    """
    if model is None or test_df is None or len(test_df) == 0:
        return None
    try:
        preds = model.predict(test_df[FEATURES].to_numpy(dtype=float))
        return float(np.mean(np.abs(preds - test_df[TARGET].to_numpy(dtype=float))))
    except Exception:
        logging.exception("Failed to evaluate model on hold-out")
        return None


def naive_holdout_mae(test_df: pd.DataFrame) -> float | None:
    """MAE of the "same as last month" forecast on a hold-out frame.

    Predicting no change means the error is the absolute change itself.
    This is the yardstick every retrain is logged against: a model that
    does not beat it adds nothing.
    """
    if test_df is None or len(test_df) == 0:
        return None
    return float(np.mean(np.abs(test_df[TARGET].to_numpy(dtype=float))))


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
    signature_context=None,
):
    data_signature = compute_data_signature(train_df, context=signature_context)
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
    naive_test_mae = None
    if has_holdout:
        candidate = train_model(train_part)
        candidate_test_mae = evaluate_model_holdout(test_part, candidate)
        naive_test_mae = naive_holdout_mae(test_part)

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
    if naive_test_mae is not None:
        metadata_payload["naive_test_mae"] = naive_test_mae
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
        "naive_test_mae": naive_test_mae,
    }


def build_score_frames(df: pd.DataFrame, population=None) -> tuple[dict, float]:
    """Compute the scored monthly frame of every Member State.

    Returns ``(frames, reference_log)`` where ``frames`` maps a geo code to
    its frame (see ``compute_rate_frame`` / ``add_score``) and
    ``reference_log`` is the log of the highest smoothed rate ever observed
    across the EU, the common scale of the score.

    Countries without a population figure are skipped with a warning: a
    per-capita score cannot be computed for them.
    """
    population = POPULATION if population is None else population
    df = df.copy()
    df["date"] = pd.to_datetime(df["date"])

    rate_frames = {}
    for geo, group in df.groupby("geo_code"):
        if geo not in population:
            logging.warning("No population figure for %s; skipping it", geo)
            continue
        rate_frames[geo] = compute_rate_frame(group, population[geo])

    max_rate = max(
        (frame["rate_per_100k"].max() for frame in rate_frames.values() if frame["rate_per_100k"].notna().any()),
        default=0.0,
    )
    reference_log = float(np.log1p(max_rate)) if max_rate > 0 else 1.0
    return {geo: add_score(frame, reference_log) for geo, frame in rate_frames.items()}, reference_log


def calculate_risk_and_predict(df, engine):
    if df.empty:
        return pd.DataFrame()

    predictions = []
    frames, reference_log = build_score_frames(df)
    logging.info("Score reference: highest smoothed rate log1p=%.4f", reference_log)

    # Every country's training target depends on the formula version and on
    # the EU-wide reference, so both belong in each model's cache signature:
    # a new all-time peak rescales every target even where the country's own
    # series did not change.
    signature_context = f"score_v{SCORE_VERSION}|reference_log={reference_log:.12f}"

    for geo, frame in frames.items():
        scored = frame.dropna(subset=["risk_score"]).copy()
        if len(scored) < 12:
            # Not enough history to learn anything from.
            continue

        # --- Model features: last score, its last change, calendar month ---
        scored["lag_1"] = scored["risk_score"].shift(1)
        scored["delta_1"] = scored["lag_1"] - scored["risk_score"].shift(2)
        scored[TARGET] = scored["risk_score"] - scored["lag_1"]
        scored["month"] = scored["date"].dt.month

        train_df = scored.dropna(subset=FEATURES + [TARGET])
        if len(train_df) < 12:
            continue

        model, model_id, model_info = get_or_train_model(
            engine, geo, train_df, signature_context=signature_context
        )
        if model_info.get("reused"):
            logging.info(
                "Model %s for %s reused (signature=%s)",
                model_id,
                geo,
                model_info.get("data_signature", ""),
            )
        else:
            logging.info(
                "Model %s for %s retrained (signature=%s, test_mae=%s, naive_test_mae=%s)",
                model_id,
                geo,
                model_info.get("data_signature", ""),
                model_info.get("test_mae"),
                model_info.get("naive_test_mae"),
            )

        # Predict M+1, M+2, M+3 from the last published month of THIS country
        # (Member States report at different speeds).
        last_row = scored.iloc[-1]
        last_date = last_row["date"]
        current_score = float(last_row["risk_score"])
        base = current_score
        last_change = float(last_row[TARGET]) if pd.notna(last_row[TARGET]) else 0.0

        for i in range(1, 4):
            next_date = last_date + pd.DateOffset(months=i)

            # The model returns the expected CHANGE; per-tree outputs give the
            # P10/P90 band of that change, added to the previous step's value.
            features = np.array([[base, last_change, next_date.month]], dtype=float)
            change, change_low, change_high = predict_with_quantiles(model, features)
            if change is None:
                change, change_low, change_high = 0.0, None, None

            pred = max(0.0, min(100.0, base + change))
            p10 = max(0.0, min(100.0, base + change_low)) if change_low is not None else None
            p90 = max(0.0, min(100.0, base + change_high)) if change_high is not None else None

            predictions.append(
                {
                    "date": last_date.date(),
                    "geo_code": geo,
                    "risk_score_calculated": current_score,
                    "applications_per_100k": float(last_row["rate_per_100k"]),
                    "trend_3m": float(last_row["trend"]),
                    "prediction_target_month": next_date.date(),
                    "predicted_risk_score": float(pred),
                    "predicted_risk_score_p10": float(p10) if p10 is not None else None,
                    "predicted_risk_score_p90": float(p90) if p90 is not None else None,
                    "model_id": model_id,
                }
            )

            # Roll forward: the forecast becomes the base of the next step.
            last_change = pred - base
            base = pred

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


def purge_old_models(engine, keep_last: int):
    """Keep only the ``keep_last`` most recent models per (model_name, geo_code).

    Every retrain INSERTs a new pickled artifact, and nothing deleted them:
    the registry grew without bound (one model per country per retrain).
    Models still referenced by retained ``risk_predictions`` rows are kept
    regardless of age so the ``model_id`` foreign key stays valid.
    """
    if keep_last <= 0:
        return

    with engine.begin() as conn:
        result = conn.execute(
            text(
                """
                DELETE FROM model_registry
                WHERE id IN (
                    SELECT id FROM (
                        SELECT id,
                               ROW_NUMBER() OVER (
                                   PARTITION BY model_name, geo_code
                                   ORDER BY trained_at DESC, id DESC
                               ) AS rn
                        FROM model_registry
                    ) ranked
                    WHERE ranked.rn > :keep
                )
                AND id NOT IN (
                    SELECT model_id FROM risk_predictions WHERE model_id IS NOT NULL
                )
                """
            ),
            {"keep": keep_last},
        )
        logging.info("Purged %s old model artifacts", result.rowcount)


@retry("DB save")
def _insert_predictions(engine, predictions_df):
    """Write the prediction batch inside a single transaction.

    ``to_sql`` on an Engine runs as one transaction, so a failed attempt
    leaves no partial rows behind and the retry decorator can safely
    re-run the whole insert. The retention purge stays OUTSIDE this
    function on purpose: retrying the insert after a purge-only failure
    would collide with the unique (run_id, geo, target_month) index.
    """
    predictions_df.to_sql(
        "risk_predictions",
        engine,
        if_exists="append",
        index=False,
        method="multi",
        chunksize=500,
    )


def save_predictions(df, engine=None, run_metadata=None):
    if df.empty:
        logging.info("No predictions to save.")
        return

    engine = engine or get_db_engine()
    logging.info("Saving %s predictions...", len(df))

    metadata = _build_run_metadata(run_metadata)

    try:
        predictions_df = df.copy()
        predictions_df["run_id"] = metadata["run_id"]
        predictions_df["prediction_date"] = metadata["prediction_date"]

        _insert_predictions(engine, predictions_df)
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
        purge_old_models(engine, MODEL_REGISTRY_KEEP_LAST)
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
        "ALTER TABLE risk_predictions "
        "ADD COLUMN IF NOT EXISTS applications_per_100k NUMERIC(8, 2)",
        "ALTER TABLE risk_predictions "
        "ADD COLUMN IF NOT EXISTS trend_3m NUMERIC(6, 3)",
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
    parser.add_argument(
        "--once", action="store_true", help="Run a single prediction job and exit (no scheduler)"
    )
    args = parser.parse_args()

    configure_logging()

    if args.healthcheck:
        healthy = check_health()
        sys.exit(0 if healthy else 1)

    # One-shot mode: run a single prediction job then exit (no resident
    # scheduler). Used by the monthly scheduler sidecar so the container holds
    # zero RAM between runs. run_job() already waits (bounded) for fresh data.
    if args.once:
        logging.info("Risk Predictor one-shot run...")
        ensure_predictions_schema()
        run_job()
        sys.exit(0)

    logging.info("Risk Predictor Service Starting...")
    time.sleep(15)  # Wait for Harvester?
    start_scheduler()
