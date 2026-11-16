"""
NOUVEAU HARVESTER SIMPLIFIÉ - Bulk Download TSV Eurostat
Remplace complètement l'ancien harvester problématique
"""

import csv
import logging
import os
import signal
import sys
import time

import pandas as pd
import requests
from sqlalchemy import create_engine, inspect, text

# Configuration logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

HEALTH_FILE = os.getenv("HARVESTER_HEALTH_FILE", "/tmp/harvester_health")
# Healthcheck considers the harvester unhealthy if the file hasn't been touched
# in HEALTH_MAX_AGE_SECONDS. Default = 25h to absorb the daily 24h scheduler.
HEALTH_MAX_AGE_SECONDS = int(os.getenv("HARVESTER_HEALTH_MAX_AGE_SECONDS", str(25 * 3600)))
STAGING_TABLE = "asylum_data_staging"

# Bump whenever the parsing or filtering rules change what ends up in
# asylum_data. The version is stored with the Eurostat freshness marker, so
# a deployment that changes the rules re-harvests on its own instead of
# trusting rows written by the previous logic.
HARVEST_FORMAT_VERSION = "2"

# Network retry policy. In one-shot mode the harvester runs once a month: a
# transient Eurostat hiccup at that exact moment would otherwise skip the
# whole month's refresh, so the download and the metadata probe both retry
# with exponential backoff before giving up.
RETRY_MAX_ATTEMPTS = int(os.getenv("RETRY_MAX_ATTEMPTS", "3"))
RETRY_BACKOFF_SECONDS = float(os.getenv("RETRY_BACKOFF_SECONDS", "2"))


def retry(operation_name):
    """Retry decorator with exponential backoff (mirrors the predictor's)."""

    def decorator(func):
        def wrapper(*args, **kwargs):
            delay = RETRY_BACKOFF_SECONDS
            for attempt in range(1, RETRY_MAX_ATTEMPTS + 1):
                try:
                    return func(*args, **kwargs)
                except Exception as exc:
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

# Identify ourselves to Eurostat in the User-Agent so the operator of the
# Eurostat dissemination service can attribute traffic. Conforms to the
# Eurostat re-use policy (see docs/DATA_CARD.md).
HARVESTER_USER_AGENT = os.getenv(
    "HARVESTER_USER_AGENT",
    "eu-border-risk-profiler/1.0 (+https://github.com/LibreArbitre/eu-border-risk-profiler)",
)
EUROSTAT_HTTP_HEADERS = {"User-Agent": HARVESTER_USER_AGENT}


def _touch_health_file() -> None:
    """Update the mtime of the health file so the container healthcheck sees a recent run."""
    try:
        with open(HEALTH_FILE, "w", encoding="utf-8") as fh:
            fh.write(str(time.time()))
    except OSError as exc:
        logging.warning(f"Could not write health file {HEALTH_FILE}: {exc}")


def _run_healthcheck() -> int:
    """Exit 0 if the harvester has run recently, else 1.

    Used by the docker-compose healthcheck. Replaces the previous always-success stub.
    """
    if not os.path.exists(HEALTH_FILE):
        print(f"health file missing: {HEALTH_FILE}")
        return 1
    age = time.time() - os.path.getmtime(HEALTH_FILE)
    if age > HEALTH_MAX_AGE_SECONDS:
        print(f"health file too old: {age:.0f}s > {HEALTH_MAX_AGE_SECONDS}s")
        return 1
    return 0


# Database connection. Memoised: every function used to create its own
# Engine (save_to_db even did so once per chunk), each holding pooled
# connections until garbage collection. One Engine per process reuses the
# pool as SQLAlchemy intends.
_ENGINE = None


def get_db_engine():
    global _ENGINE
    if _ENGINE is None:
        db_host = os.getenv("DB_HOST", "db")
        db_user = os.getenv("DB_USER", "user")
        db_pass = os.getenv("DB_PASSWORD", "password")
        db_name = os.getenv("DB_NAME", "eubrp_db")
        _ENGINE = create_engine(f"postgresql://{db_user}:{db_pass}@{db_host}:5432/{db_name}")
    return _ENGINE


def init_meta_table():
    """Crée la table de métadonnées si elle n'existe pas"""
    engine = get_db_engine()
    with engine.connect() as conn:
        conn.execute(
            text("""
            CREATE TABLE IF NOT EXISTS harvester_meta (
                key VARCHAR(50) PRIMARY KEY,
                value VARCHAR(255),
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        )
        conn.commit()


def get_local_last_modified():
    """Récupère la date de dernière modif stockée en base"""
    engine = get_db_engine()
    try:
        with engine.connect() as conn:
            # Vérifier d'abord si la table existe
            inspector = inspect(engine)
            if not inspector.has_table("harvester_meta"):
                return None

            result = conn.execute(
                text("SELECT value FROM harvester_meta WHERE key = 'eurostat_last_modified'")
            ).fetchone()

            if result:
                return result[0]
    except Exception as e:
        logging.warning(f"Could not read local meta: {e}")
    return None


def update_local_last_modified(last_modified_str):
    """Met à jour la date en base"""
    engine = get_db_engine()
    with engine.begin() as conn:
        conn.execute(
            text("""
            INSERT INTO harvester_meta (key, value, updated_at)
            VALUES ('eurostat_last_modified', :val, NOW())
            ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = NOW()
        """),
            {"val": last_modified_str},
        )


# Single-cell JSON-stat probe. The payload is around one kilobyte and
# carries the dataset-level `updated` field, which Eurostat keeps
# accurate for every new publication and revision. The exact filter
# values don't matter — we only consume the metadata, not the cell.
EUROSTAT_METADATA_PROBE_URL = (
    "https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/"
    "migr_asyappctzm?lastTimePeriod=1&geo=FR&applicant=FRST&age=TOTAL"
    "&sex=T&unit=PER&citizen=SY"
)


@retry("Eurostat metadata probe")
def _fetch_remote_updated_at() -> str | None:
    response = requests.get(
        EUROSTAT_METADATA_PROBE_URL,
        timeout=30,
        headers=EUROSTAT_HTTP_HEADERS,
    )
    response.raise_for_status()
    return response.json().get("updated")


def get_remote_updated_at() -> str | None:
    """Return the dataset's official `updated` timestamp from Eurostat.

    Probes the JSON-stat endpoint with a one-cell filter so we transfer
    ~1 KB instead of the 440 MB bulk file just to check freshness. The
    returned value is an ISO-8601 string like
    ``"2026-05-05T11:00:00+0200"`` and is treated as an opaque cache key:
    we only ever compare it for equality with the previously stored
    value. Retries transient failures, then returns ``None`` — callers
    fall back to the cached snapshot (or a re-download on first run).
    """
    try:
        return _fetch_remote_updated_at()
    except Exception as exc:
        logging.error(f"Failed to probe Eurostat metadata: {exc}")
        return None


@retry("Eurostat bulk download")
def download_eurostat_tsv(url):
    """
    Télécharge le fichier TSV complet depuis Eurostat vers le disque.
    Dataset: migr_asyappctzm (Asylum applications by citizenship)

    Retourne le CHEMIN du fichier téléchargé (pas son contenu) : le TSV
    fait ~440 Mo et le charger entièrement en RAM puis le dupliquer en
    ``StringIO`` faisait grimper la mémoire à plusieurs Go. Le parsing
    en aval lit directement depuis le disque en flux via ``pd.read_csv``.
    """
    logging.info("Downloading Eurostat TSV bulk file...")

    # Download with stream to avoid memory issues and show progress
    local_filename = "/tmp/eurostat_data.tsv"
    try:
        with requests.get(url, stream=True, timeout=120, headers=EUROSTAT_HTTP_HEADERS) as r:
            r.raise_for_status()
            downloaded = 0
            with open(local_filename, "wb") as f:
                for chunk in r.iter_content(chunk_size=8192):
                    f.write(chunk)
                    downloaded += len(chunk)
                    if downloaded % (10 * 1024 * 1024) < 8192:  # Log every ~10MB
                        logging.info(f"Downloaded {downloaded / (1024 * 1024):.1f} MB...")

        logging.info(f"Download complete. Total size: {downloaded / (1024 * 1024):.1f} MB")

        return local_filename

    except Exception as e:
        logging.error(f"Download failed: {e}")
        raise


def process_and_save_chunked(tsv_path, chunk_size=100000):
    """
    Parse le TSV Eurostat en chunks et sauvegarde au fur et à mesure.
    OPTIMISÉ: Filtre et agrège AVANT le melt pour réduire la consommation mémoire.
    FIX: dtype=str pour éviter les DtypeVerify warnings

    ``tsv_path`` est le chemin du fichier téléchargé ; ``pd.read_csv`` le
    lit en flux depuis le disque (au lieu d'un ``StringIO`` en RAM), ce
    qui évite de garder l'intégralité des ~440 Mo en mémoire.
    """
    logging.info("Starting optimized chunked processing...")

    # EU countries to keep
    EU_COUNTRIES = {
        "AT",
        "BE",
        "BG",
        "CY",
        "CZ",
        "DE",
        "DK",
        "EE",
        "EL",
        "ES",
        "FI",
        "FR",
        "HR",
        "HU",
        "IE",
        "IT",
        "LT",
        "LU",
        "LV",
        "MT",
        "NL",
        "PL",
        "PT",
        "RO",
        "SE",
        "SI",
        "SK",
    }

    try:
        # First read header to get columns
        header_df = pd.read_csv(
            tsv_path, sep="\t", engine="c", quoting=csv.QUOTE_NONE, on_bad_lines="warn", nrows=0,
            encoding="utf-8",
        )
        header_df.columns = header_df.columns.str.strip()
        columns = header_df.columns.tolist()

        # Define iterator
        # FIX: dtype=str forces all columns to be read as strings initially.
        # This prevents pandas from inferring int then crashing on ':', 'p', etc.
        chunk_iter = pd.read_csv(
            tsv_path,
            sep="\t",
            engine="c",
            quoting=csv.QUOTE_NONE,
            on_bad_lines="warn",
            chunksize=chunk_size,
            names=columns,
            header=0,
            dtype=str,  # <--- CRITICAL FIX FOR WARNINGS
            encoding="utf-8",
        )

        total_rows = 0

        for i, df in enumerate(chunk_iter):
            logging.info(f"Processing chunk {i + 1} ({len(df)} rows)...")

            # Clean columns
            df.columns = df.columns.str.strip()

            # La première colonne contient toutes les dimensions concaténées
            dimension_col = df.columns[0]

            # Séparer les dimensions
            dimensions = df[dimension_col].str.split(",", expand=True)

            if dimensions.shape[1] != 7:
                logging.warning(f"Chunk {i + 1}: Unexpected dimensions {dimensions.shape[1]}, skipping")
                continue

            dimensions.columns = ["freq", "unit", "citizen", "sex", "applicant", "age", "geo"]

            # ==== Filtrage avant melt (économise mémoire et CPU) ====
            valid_mask = select_rows(dimensions, EU_COUNTRIES)

            filtered_count = valid_mask.sum()
            if filtered_count == 0:
                logging.info(f"Chunk {i + 1}: No valid rows after filter, skipping")
                continue

            logging.info(
                f"Chunk {i + 1}: Filtered to {filtered_count} rows "
                "(FRST + EU + all sexes + all ages + ISO-2 or TOTAL citizen)"
            )

            # Appliquer le filtre au DataFrame original
            df_filtered = df[valid_mask].copy()
            dimensions_filtered = dimensions[valid_mask].copy()

            # Reconstruire avec dimensions, citizen incluse cette fois pour
            # exposer la ventilation par nationalité.
            df_filtered = pd.concat(
                [
                    dimensions_filtered[["geo", "citizen", "applicant"]].reset_index(drop=True),
                    df_filtered.drop(columns=[dimension_col]).reset_index(drop=True),
                ],
                axis=1,
            )

            # Les colonnes de dates sont tout sauf les colonnes de dimensions.
            date_cols = [c for c in df_filtered.columns if c not in ["geo", "citizen", "applicant"]]

            # Valeurs numériques ; une cellule non publiée (":") reste NaN.
            for col in date_cols:
                df_filtered[col] = parse_values(df_filtered[col])

            df_final = aggregate_chunk_to_long(df_filtered, date_cols)
            n_geos = df_final["geo_code"].nunique()
            logging.info(f"Chunk {i + 1}: Aggregated to {len(df_final)} published values ({n_geos} geos)")

            # Select final columns
            final_cols = ["date", "geo_code", "citizen_code", "applicant_type", "total_applications"]
            if not df_final.empty:
                df_final = df_final[final_cols]
                save_to_db(df_final)
                total_rows += len(df_final)
                logging.info(f"Chunk {i + 1}: Saved {len(df_final)} records")

            # Libérer la mémoire
            del (
                df,
                dimensions,
                df_filtered,
                dimensions_filtered,
                df_final,
            )

        logging.info(f"Total records saved: {total_rows}")

    except Exception as e:
        logging.error(f"Chunk processing failed: {e}")
        raise


def reset_staging_table():
    """(Re)create the staging table as a clean copy of asylum_data's structure.

    All chunks are written here first; the production table is only swapped
    in after the full harvest succeeds (see ``promote_staging_to_production``).
    """
    engine = get_db_engine()
    with engine.begin() as conn:
        conn.execute(text(f"DROP TABLE IF EXISTS {STAGING_TABLE}"))
        # Use a regular table (not UNLOGGED) so the data is durable while we
        # process chunks; the swap step relies on it being readable.
        conn.execute(
            text(
                f"""
                CREATE TABLE {STAGING_TABLE} (
                    id SERIAL PRIMARY KEY,
                    date DATE NOT NULL,
                    geo_code VARCHAR(10) NOT NULL,
                    citizen_code VARCHAR(10) NOT NULL,
                    applicant_type VARCHAR(50) NOT NULL,
                    total_applications INTEGER,
                    extraction_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
        )
        conn.execute(
            text(
                f"""
                CREATE UNIQUE INDEX idx_{STAGING_TABLE}_unique
                ON {STAGING_TABLE} (date, geo_code, citizen_code, applicant_type)
                """
            )
        )
    logging.info(f"Staging table {STAGING_TABLE} prepared.")


def promote_staging_to_production():
    """Atomically replace asylum_data with the freshly loaded staging data.

    Runs the swap inside a single transaction so a crash mid-swap rolls back
    and leaves the existing production table untouched. This replaces the
    previous behavior where ``TRUNCATE asylum_data`` ran before the inserts,
    leaving the table empty if the harvest failed afterwards.
    """
    engine = get_db_engine()
    with engine.begin() as conn:
        conn.execute(text("TRUNCATE TABLE asylum_data"))
        conn.execute(
            text(
                f"""
                INSERT INTO asylum_data
                    (date, geo_code, citizen_code, applicant_type, total_applications, extraction_date)
                SELECT date, geo_code, citizen_code, applicant_type, total_applications, extraction_date
                FROM {STAGING_TABLE}
                """
            )
        )
        conn.execute(text(f"DROP TABLE {STAGING_TABLE}"))
    logging.info("✅ Staging promoted to asylum_data atomically.")


SAVE_BATCH_SIZE = 5000


def select_rows(dimensions: pd.DataFrame, eu_countries) -> pd.Series:
    """Boolean mask of the TSV rows the project keeps.

    The bulk file carries one row per combination of every dimension,
    INCLUDING the pre-aggregated ones: ``sex`` has ``T`` (total) next to
    ``M``/``F``/``UNK`` and ``age`` has ``TOTAL`` next to every age band
    (and ``Y_LT18`` next to its two sub-bands). Summing all rows of a
    (geo, citizen) pair therefore counts each applicant four to five times.
    Only the ``sex=T`` / ``age=TOTAL`` row is the real figure.

    Citizenship keeps the ISO-3166 alpha-2 codes for the per-nationality
    breakdown plus Eurostat's own ``TOTAL`` row, which is the official
    country-level figure (it includes stateless and unknown citizenships,
    which a sum of the alpha-2 rows would miss).
    """
    citizen = dimensions["citizen"]
    return (
        (dimensions["applicant"] == "FRST")
        & dimensions["geo"].isin(eu_countries)
        & (dimensions["sex"] == "T")
        & (dimensions["age"] == "TOTAL")
        & (citizen.str.match(r"^[A-Z]{2}$", na=False) | (citizen == "TOTAL"))
    )


def parse_values(cells: pd.Series) -> pd.Series:
    """Turn raw TSV cells into numbers, keeping "not published" as NaN.

    Cells look like ``"8665"``, ``"8665 p"`` (flagged) or ``": "`` (not
    available). A missing cell must NOT become 0: a month a Member State
    has not reported yet is unknown, and storing 0 made such countries
    look like their applications had collapsed.
    """
    digits = cells.astype(str).str.replace(r"[^0-9.]", "", regex=True)
    return pd.to_numeric(digits, errors="coerce")


def aggregate_chunk_to_long(df_dim_wide: pd.DataFrame, date_cols: list) -> pd.DataFrame:
    """Reshape a filtered wide-format chunk into a long-format frame.

    Input is a chunk already reduced by ``select_rows`` (one row per
    (geo, citizen), ``TOTAL`` included) with columns ``geo``, ``citizen``,
    ``applicant`` plus the date columns listed in ``date_cols``, parsed by
    ``parse_values``.

    Output columns: ``date``, ``geo_code``, ``citizen_code``,
    ``applicant_type``, ``total_applications``. Only published values are
    emitted: a NaN cell produces no row, a genuine 0 does.

    Pure function (no I/O), covered by unit tests.
    """
    columns = ["date", "geo_code", "citizen_code", "applicant_type", "total_applications"]
    if df_dim_wide.empty or not date_cols:
        return pd.DataFrame(columns=columns)

    # One row per (geo, citizen) is expected; min_count keeps an all-missing
    # cell missing instead of turning it into 0 if duplicates ever show up.
    df_agg = df_dim_wide.groupby(["geo", "citizen"])[date_cols].sum(min_count=1).reset_index()
    df_agg["applicant"] = "FRST"

    df_long = df_agg.melt(
        id_vars=["geo", "citizen", "applicant"],
        var_name="date_raw",
        value_name="total_applications",
    )
    df_long = df_long[df_long["date_raw"].str.match(r"^\d{4}-\d{2}$", na=False)]
    df_long["date"] = pd.to_datetime(df_long["date_raw"] + "-01", format="%Y-%m-%d", errors="coerce")
    df_long = df_long.dropna(subset=["date", "total_applications"])
    df_long["total_applications"] = df_long["total_applications"].astype(int)

    df_final = df_long.rename(
        columns={"geo": "geo_code", "citizen": "citizen_code", "applicant": "applicant_type"}
    )

    return df_final[columns].reset_index(drop=True)


def save_to_db(df):
    """Write a chunk into the staging table with summing-UPSERT semantics.

    Multiple chunks may contain rows for the same (date, geo, citizen,
    applicant) tuple because the source TSV is split positionally; we sum
    them so the staging table ends up with the full per-key total before
    promotion.

    Rows are sent in batches via SQLAlchemy ``executemany`` rather than one
    INSERT per row — important now that retaining the per-citizen breakdown
    multiplies the row count by ~150×.
    """
    if df.empty:
        logging.info("No data to save")
        return

    logging.info(f"Saving {len(df)} records to staging table...")

    engine = get_db_engine()

    upsert_stmt = text(
        f"""
        INSERT INTO {STAGING_TABLE} (date, geo_code, citizen_code, applicant_type, total_applications)
        VALUES (:date, :geo_code, :citizen_code, :applicant_type, :total_applications)
        ON CONFLICT (date, geo_code, citizen_code, applicant_type)
        DO UPDATE SET total_applications = {STAGING_TABLE}.total_applications + EXCLUDED.total_applications
        """
    )

    records = df[["date", "geo_code", "citizen_code", "applicant_type", "total_applications"]].to_dict(
        orient="records"
    )

    with engine.begin() as conn:
        for start in range(0, len(records), SAVE_BATCH_SIZE):
            batch = records[start : start + SAVE_BATCH_SIZE]
            conn.execute(upsert_stmt, batch)

    logging.info("✅ Chunk saved to staging")


def run_harvest():
    """
    Fonction principale du harvester
    """
    logging.info("=" * 60)
    logging.info("EUROSTAT TSV BULK DOWNLOAD HARVESTER")
    logging.info("=" * 60)

    url = "https://ec.europa.eu/eurostat/api/dissemination/sdmx/2.1/data/migr_asyappctzm/?format=TSV&compressed=false"

    try:
        # 0. Init Meta Table
        init_meta_table()

        # 0.5 Probe Eurostat for the dataset's official `updated` timestamp.
        #     Falls back to a re-download when the probe fails or the
        #     timestamp differs from the stored one.
        logging.info("Probing Eurostat metadata...")
        remote_updated = get_remote_updated_at()
        local_updated = get_local_last_modified()
        format_suffix = f"|fmt{HARVEST_FORMAT_VERSION}"
        remote_marker = f"{remote_updated}{format_suffix}" if remote_updated else None

        logging.info(f"Remote updated: {remote_updated}")
        logging.info(f"Local updated:  {local_updated}")

        if remote_marker and remote_marker == local_updated:
            # Touch the health file so a quiet day doesn't make us look stale
            # to the docker healthcheck — we DID check, we just had nothing
            # to do. asylum_data is unchanged from the previous successful
            # swap so downstream services keep seeing valid data.
            _touch_health_file()
            logging.info("✅ Data is up to date. No new download needed.")
            logging.info("=" * 60)
            return

        if remote_updated is None and local_updated is not None and local_updated.endswith(format_suffix):
            # The metadata probe failed (timeout, 5xx, schema change…) but we
            # already have a previously stored marker. Don't waste 6-8 min of
            # CPU + 440 MB of bandwidth chasing a remote freshness signal we
            # couldn't read; trust the cache and try again on the next cycle.
            _touch_health_file()
            logging.warning(
                "Remote freshness probe returned None — keeping the cached "
                "snapshot and skipping this cycle."
            )
            logging.info("=" * 60)
            return

        logging.info("Update detected or first run. Proceeding with bulk download...")

        # 1. Télécharger le TSV (sur disque, pas en RAM)
        tsv_path = download_eurostat_tsv(url)

        # 1.5 Préparer la table de staging (vide). asylum_data n'est PAS touchée.
        reset_staging_table()

        # 2. Parser et Sauvegarder en chunks dans la staging
        process_and_save_chunked(tsv_path)

        # 2.5 Swap atomique staging -> asylum_data
        promote_staging_to_production()

        # 3. Persister le timestamp de fraîcheur pour le prochain cycle.
        if remote_marker:
            update_local_last_modified(remote_marker)
            logging.info(f"Updated local freshness marker to: {remote_marker}")

        _touch_health_file()
        logging.info("=" * 60)
        logging.info("✅ HARVEST COMPLETED SUCCESSFULLY")
        logging.info("=" * 60)

    except Exception as e:
        logging.error(f"❌ Harvest failed: {e}", exc_info=True)
        raise


_shutdown = False


def _request_shutdown(signum, _frame):
    global _shutdown
    logging.info(f"Received signal {signum}, shutting down after current cycle.")
    _shutdown = True


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--healthcheck":
        sys.exit(_run_healthcheck())

    # One-shot mode: run a single harvest then exit (no resident daemon).
    # Used by the monthly scheduler sidecar so the container holds zero RAM
    # between runs instead of sleeping 24/7 with the full heap loaded.
    if len(sys.argv) > 1 and sys.argv[1] == "--once":
        run_harvest()
        sys.exit(0)

    signal.signal(signal.SIGTERM, _request_shutdown)
    signal.signal(signal.SIGINT, _request_shutdown)

    # Do NOT touch the health file pre-emptively. The container should only
    # report healthy once the first run_harvest() succeeds — that's how
    # downstream services (risk_predictor) know the staging swap is done.
    # The compose `start_period` covers the long initial download.

    # Run harvest immediately on startup
    run_harvest()

    # Then re-run on a daily cadence with a sleep loop that respects SIGTERM.
    logging.info("Scheduler started. Next run in ~24h.")
    while not _shutdown:
        # Sleep in small slices so SIGTERM is acknowledged within seconds.
        for _ in range(86400):
            if _shutdown:
                break
            time.sleep(1)
        if _shutdown:
            break
        try:
            run_harvest()
        except Exception:
            # Logged inside run_harvest; rely on docker restart policy and
            # health file staleness rather than crashing the whole process.
            pass

    logging.info("Harvester exited cleanly.")
