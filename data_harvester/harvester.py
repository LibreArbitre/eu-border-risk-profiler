import argparse
import logging
import os
import sys
import time
import schedule
import requests
import pandas as pd
from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy import table, column
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
HEALTH_FILE = os.getenv('HARVESTER_HEALTH_FILE', '/tmp/harvester_health')

DATABASE_URL = f"postgresql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"

# API URL
BASE_URL = "https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/migr_asyappctzm"
# Parameters: First time applicant, Total Age, Total Sex, Person Unit, Total Citizenship
# Using lastTimePeriod to avoid 413 Payload Too Large
PARAMS = {
    'format': 'JSON',
    'lang': 'en',
    'applicant': 'NASY_APP',
    'age': 'TOTAL',
    'sex': 'T',
    'unit': 'PER',
    'citizen': 'TOTAL',
    'lastTimePeriod': '60'
}


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


def get_db_engine():
    return create_engine(DATABASE_URL)


@retry("Eurostat fetch")
def fetch_eurostat_data():
    logging.info("Fetching data from Eurostat...")
    response = requests.get(BASE_URL, params=PARAMS, timeout=30)
    response.raise_for_status()
    return response.json()

def parse_eurostat_json(data):
    """
    Parses Eurostat JSON-stat format into a list of records.
    """
    if not data or 'value' not in data or 'dimension' not in data:
        return pd.DataFrame()

    # Extract dimensions
    dims = data['dimension']
    ids = data['id'] # Order of dimensions e.g. ['freq', 'unit', 'asyl_app', 'age', 'sex', 'citizen', 'geo', 'time']

    values = data['value']
    dimensions_map = {}
    sizes = []

    # Prepare dimension mappings
    for dim_id in ids:
        dim_info = dims[dim_id]
        # category['index'] maps Code -> Index (e.g. 'FR' -> 5)
        idx_map = dim_info['category']['index']
        # We need Index -> Code
        inv_map = {int(v): k for k, v in idx_map.items()}
        dimensions_map[dim_id] = inv_map
        sizes.append(len(inv_map))

    records = []

    # Calculate strides for index decoding
    strides = [1] * len(sizes)
    for i in range(len(sizes) - 2, -1, -1):
        strides[i] = strides[i+1] * sizes[i+1]

    # Iterate over values
    for k, v in values.items():
        try:
            idx = int(k)
        except ValueError:
            continue

        coords = {}

        # Decode index into dimension codes
        for i, dim_id in enumerate(ids):
            # Coordinate index for this dimension
            pos = (idx // strides[i]) % sizes[i]
            # Map back to code
            coords[dim_id] = dimensions_map[dim_id][pos]

        # Extract relevant fields
        time_str = coords.get('time')
        geo = coords.get('geo')
        citizen = coords.get('citizen')
        app_type = coords.get('asyl_app')

        # Convert time 2023M01 to 2023-01-01
        if time_str and 'M' in time_str:
            y, m = time_str.split('M')
            date_str = f"{y}-{m}-01"
        else:
            continue

        records.append({
            'date': date_str,
            'geo_code': geo,
            'citizen_code': citizen,
            'applicant_type': app_type,
            'total_applications': v
        })

    return pd.DataFrame(records)

def clean_data(df):
    if df.empty:
        return df
    # Ensure numeric
    df['total_applications'] = pd.to_numeric(df['total_applications'], errors='coerce').fillna(0).astype(int)
    return df

@retry("DB save")
def save_to_db(df):
    if df.empty:
        logging.info("No data to save.")
        return

    engine = get_db_engine()

    logging.info("Saving %s records to DB...", len(df))

    try:
        with engine.connect() as conn:
            # We'll use a transaction
            trans = conn.begin()
            try:
                # Define table abstraction for insert
                asylum_table = table('asylum_data',
                    column('date'),
                    column('geo_code'),
                    column('citizen_code'),
                    column('applicant_type'),
                    column('total_applications')
                )

                # Convert date string to proper format if needed, but PG handles 'YYYY-MM-DD'

                data_to_insert = df.to_dict(orient='records')

                # Chunk it to avoid huge queries
                chunk_size = 2000
                for i in range(0, len(data_to_insert), chunk_size):
                    chunk = data_to_insert[i:i+chunk_size]
                    stmt = insert(asylum_table).values(chunk)
                    # UPSERT: Update total_applications if conflict
                    stmt = stmt.on_conflict_do_update(
                        index_elements=['date', 'geo_code', 'citizen_code', 'applicant_type'],
                        set_={'total_applications': stmt.excluded.total_applications}
                    )
                    conn.execute(stmt)

                trans.commit()
                logging.info("Data saved successfully.")
            except Exception as e:
                trans.rollback()
                logging.exception("Error saving to DB")
                raise e
    except Exception as e:
         logging.exception("DB Connection failed")
         raise e


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

def run_harvest():
    logging.info("--- Starting Harvest Job ---")
    success = True
    message = ""
    try:
        data_json = fetch_eurostat_data()
        if not data_json:
            raise ValueError("No data returned from Eurostat")
        df = parse_eurostat_json(data_json)
        logging.info("Parsed %s records.", len(df))
        df = clean_data(df)
        save_to_db(df)
    except Exception as exc:  # noqa: PERF203 logging
        success = False
        message = str(exc)
        logging.exception("Harvest job failed")
        if EXIT_ON_FAILURE:
            write_health(False, message)
            sys.exit(1)
    finally:
        write_health(success, message)
    logging.info("--- Harvest Job Finished ---")

def start_scheduler():
    # Run once immediately
    run_harvest()

    # Schedule every day
    schedule.every().day.at("02:00").do(run_harvest)

    logging.info("Scheduler started. Waiting for jobs...")
    while True:
        schedule.run_pending()
        time.sleep(60)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Data harvester service")
    parser.add_argument("--healthcheck", action="store_true", help="Run healthcheck and exit")
    args = parser.parse_args()

    configure_logging()

    if args.healthcheck:
        healthy = check_health()
        sys.exit(0 if healthy else 1)

    logging.info("Data Harvester Service Starting...")
    # Wait for DB to be ready (rudimentary check or just sleep)
    time.sleep(10)
    start_scheduler()
