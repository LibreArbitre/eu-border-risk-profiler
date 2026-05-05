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
from io import StringIO

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


# Database connection
def get_db_engine():
    db_host = os.getenv("DB_HOST", "db")
    db_user = os.getenv("DB_USER", "user")
    db_pass = os.getenv("DB_PASSWORD", "password")
    db_name = os.getenv("DB_NAME", "eubrp_db")

    return create_engine(f"postgresql://{db_user}:{db_pass}@{db_host}:5432/{db_name}")


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


def get_remote_details(url):
    """Récupère les headers du fichier distant sans télécharger"""
    try:
        response = requests.head(url, timeout=30)
        response.raise_for_status()
        return response.headers.get("Last-Modified"), int(response.headers.get("Content-Length", 0))
    except Exception as e:
        logging.error(f"Failed to check remote file: {e}")
        raise


def download_eurostat_tsv(url):
    """
    Télécharge le fichier TSV complet depuis Eurostat
    Dataset: migr_asyappctzm (Asylum applications by citizenship)
    """
    logging.info("Downloading Eurostat TSV bulk file...")

    # Download with stream to avoid memory issues and show progress
    local_filename = "/tmp/eurostat_data.tsv"
    try:
        with requests.get(url, stream=True, timeout=120) as r:
            r.raise_for_status()
            downloaded = 0
            with open(local_filename, "wb") as f:
                for chunk in r.iter_content(chunk_size=8192):
                    f.write(chunk)
                    downloaded += len(chunk)
                    if downloaded % (10 * 1024 * 1024) < 8192:  # Log every ~10MB
                        logging.info(f"Downloaded {downloaded / (1024 * 1024):.1f} MB...")

        logging.info(f"Download complete. Total size: {downloaded / (1024 * 1024):.1f} MB")

        # Read file content for parsing
        with open(local_filename, "r", encoding="utf-8") as f:
            tsv_content = f.read()

        return tsv_content

    except Exception as e:
        logging.error(f"Download failed: {e}")
        raise


def process_and_save_chunked(tsv_content, chunk_size=100000):
    """
    Parse le TSV Eurostat en chunks et sauvegarde au fur et à mesure.
    OPTIMISÉ: Filtre et agrège AVANT le melt pour réduire la consommation mémoire.
    FIX: dtype=str pour éviter les DtypeVerify warnings
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
            StringIO(tsv_content), sep="\t", engine="c", quoting=csv.QUOTE_NONE, on_bad_lines="warn", nrows=0
        )
        header_df.columns = header_df.columns.str.strip()
        columns = header_df.columns.tolist()

        # Define iterator
        # FIX: dtype=str forces all columns to be read as strings initially.
        # This prevents pandas from inferring int then crashing on ':', 'p', etc.
        chunk_iter = pd.read_csv(
            StringIO(tsv_content),
            sep="\t",
            engine="c",
            quoting=csv.QUOTE_NONE,
            on_bad_lines="warn",
            chunksize=chunk_size,
            names=columns,
            header=0,
            dtype=str,  # <--- CRITICAL FIX FOR WARNINGS
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

            # ==== OPTIMISATION CLEF: Filtrer AVANT le melt ====
            # 1. Filtrer applicant == 'FRST'
            frst_mask = dimensions["applicant"] == "FRST"
            # 2. Filtrer geo dans EU
            eu_mask = dimensions["geo"].isin(EU_COUNTRIES)
            # Combiner les masques
            valid_mask = frst_mask & eu_mask

            filtered_count = valid_mask.sum()
            if filtered_count == 0:
                logging.info(f"Chunk {i + 1}: No valid rows after filter, skipping")
                continue

            logging.info(f"Chunk {i + 1}: Filtered to {filtered_count} rows (FRST + EU)")

            # Appliquer le filtre au DataFrame original
            df_filtered = df[valid_mask].copy()
            dimensions_filtered = dimensions[valid_mask].copy()

            # Reconstruire avec dimensions
            df_filtered = pd.concat(
                [
                    dimensions_filtered[["geo", "applicant"]].reset_index(drop=True),
                    df_filtered.drop(columns=[dimension_col]).reset_index(drop=True),
                ],
                axis=1,
            )

            # ==== OPTIMISATION: Agréger par geo_code AVANT le melt ====
            # Les colonnes de dates sont tout sauf 'geo' et 'applicant'
            date_cols = [c for c in df_filtered.columns if c not in ["geo", "applicant"]]

            # Convertir les valeurs en numériques (gérer les ': ' et espaces)
            for col in date_cols:
                # remove non-numeric chars except dot
                df_filtered[col] = df_filtered[col].str.replace(r"[^0-9.]", "", regex=True)
                # Coerce to numeric, fillna 0, then int
                df_filtered[col] = pd.to_numeric(df_filtered[col], errors="coerce").fillna(0).astype(int)

            # Grouper par geo et sommer toutes les nationalités/sexes/âges
            df_agg = df_filtered.groupby("geo")[date_cols].sum().reset_index()
            df_agg["applicant"] = "FRST"

            logging.info(f"Chunk {i + 1}: Aggregated to {len(df_agg)} rows (by geo_code)")

            # Maintenant le melt sur un DataFrame BEAUCOUP plus petit (27 lignes max)
            df_long = df_agg.melt(id_vars=["geo", "applicant"], var_name="date_raw", value_name="total_applications")

            # Parse dates - support YYYY-MM format
            df_long = df_long[df_long["date_raw"].str.match(r"^\d{4}-\d{2}$", na=False)]
            df_long["date"] = pd.to_datetime(df_long["date_raw"] + "-01", format="%Y-%m-%d", errors="coerce")
            df_long = df_long.dropna(subset=["date"])

            # Rename et préparer pour la DB
            df_final = df_long.rename(columns={"geo": "geo_code", "applicant": "applicant_type"})

            # Ajouter citizen_code comme 'TOTAL' (agrégé)
            df_final["citizen_code"] = "TOTAL"

            # Select final columns
            final_cols = ["date", "geo_code", "citizen_code", "applicant_type", "total_applications"]
            if not df_final.empty:
                df_final = df_final[final_cols]
                save_to_db(df_final)
                total_rows += len(df_final)
                logging.info(f"Chunk {i + 1}: Saved {len(df_final)} records")

            # Libérer la mémoire
            del df, dimensions, df_filtered, dimensions_filtered, df_agg, df_long, df_final

        logging.info(f"Total records saved: {total_rows}")

    except Exception as e:
        logging.error(f"Chunk processing failed: {e}")
        raise


def filter_data(df):
    """
    Filtre les données pour ne garder que ce qui nous intéresse
    """
    logging.info(f"Filtering data... Starting with {len(df)} rows")

    # Filtrer pour First-time applicants (FRST)
    if "applicant_type" in df.columns:
        df = df[df["applicant_type"] == "FRST"].copy()
        logging.info(f"After FRST filter: {len(df)} rows")

    # NOTE: On ne filtre plus sur citizen_code == 'TOTAL' car le dataset n'a pas cette valeur agrégée
    # Le citizen_code contient des codes pays individuels (AD, AE, AF, etc.)
    # On garde toutes les nationalités pour une analyse complète

    # Filtrer pour les 27 pays UE
    eu_countries = [
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
    ]

    df = df[df["geo_code"].isin(eu_countries)].copy()
    logging.info(f"After EU filter: {len(df)} rows")

    # Dédupliquer
    before = len(df)
    df = df.drop_duplicates(subset=["date", "geo_code", "citizen_code", "applicant_type"], keep="last")
    after = len(df)

    if before != after:
        logging.info(f"Removed {before - after} duplicates")

    return df


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


def save_to_db(df):
    """Write a chunk into the staging table with summing-UPSERT semantics.

    Multiple chunks may contain rows for the same (date, geo, citizen,
    applicant) tuple because the source TSV is split positionally; we sum
    them so the staging table ends up with the full per-key total before
    promotion.
    """
    if df.empty:
        logging.info("No data to save")
        return

    logging.info(f"Saving {len(df)} records to staging table...")

    engine = get_db_engine()

    with engine.begin() as conn:
        for _, row in df.iterrows():
            conn.execute(
                text(
                    f"""
                    INSERT INTO {STAGING_TABLE} (date, geo_code, citizen_code, applicant_type, total_applications)
                    VALUES (:date, :geo_code, :citizen_code, :applicant_type, :total_applications)
                    ON CONFLICT (date, geo_code, citizen_code, applicant_type)
                    DO UPDATE SET total_applications = {STAGING_TABLE}.total_applications + EXCLUDED.total_applications
                    """
                ),
                {
                    "date": row["date"],
                    "geo_code": row["geo_code"],
                    "citizen_code": row["citizen_code"],
                    "applicant_type": row["applicant_type"],
                    "total_applications": row["total_applications"],
                },
            )

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

        # 0.5 Check Last-Modified
        logging.info("Checking remote file info...")
        remote_last_mod, remote_size = get_remote_details(url)
        local_last_mod = get_local_last_modified()

        logging.info(f"Remote Last-Modified: {remote_last_mod}")
        logging.info(f"Local Last-Modified:  {local_last_mod}")

        if remote_last_mod and remote_last_mod == local_last_mod:
            # Touch the health file so a quiet day doesn't make us look stale
            # to the docker healthcheck — we DID check, we just had nothing
            # to do. asylum_data is unchanged from the previous successful
            # swap so downstream services keep seeing valid data.
            _touch_health_file()
            logging.info("✅ Data is up to date. No new download needed.")
            logging.info("=" * 60)
            return

        logging.info(
            f"Update detected or first run. Proceeding with download ({remote_size / (1024 * 1024):.1f} MB)..."
        )

        # 1. Télécharger le TSV
        tsv_content = download_eurostat_tsv(url)

        # 1.5 Préparer la table de staging (vide). asylum_data n'est PAS touchée.
        reset_staging_table()

        # 2. Parser et Sauvegarder en chunks dans la staging
        process_and_save_chunked(tsv_content)

        # 2.5 Swap atomique staging -> asylum_data
        promote_staging_to_production()

        # 3. Update Last-Modified
        if remote_last_mod:
            update_local_last_modified(remote_last_mod)
            logging.info(f"Updated local Last-Modified to: {remote_last_mod}")

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
