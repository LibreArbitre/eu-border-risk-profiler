import os
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

def get_db_engine():
    return create_engine(DATABASE_URL)

def fetch_eurostat_data():
    print(f"[{datetime.now()}] Fetching data from Eurostat...", flush=True)
    try:
        response = requests.get(BASE_URL, params=PARAMS)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        print(f"Error fetching data: {e}", flush=True)
        return None

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

def save_to_db(df):
    if df.empty:
        print("No data to save.", flush=True)
        return

    engine = get_db_engine()

    print(f"Saving {len(df)} records to DB...", flush=True)

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
                print("Data saved successfully.", flush=True)
            except Exception as e:
                trans.rollback()
                print(f"Error saving to DB: {e}", flush=True)
                raise e
    except Exception as e:
         print(f"DB Connection failed: {e}", flush=True)

def run_harvest():
    print(f"--- Starting Harvest Job at {datetime.now()} ---", flush=True)
    data_json = fetch_eurostat_data()
    if data_json:
        df = parse_eurostat_json(data_json)
        print(f"Parsed {len(df)} records.", flush=True)
        df = clean_data(df)
        save_to_db(df)
    print("--- Harvest Job Finished ---", flush=True)

def start_scheduler():
    # Run once immediately
    run_harvest()

    # Schedule every day
    schedule.every().day.at("02:00").do(run_harvest)

    print("Scheduler started. Waiting for jobs...", flush=True)
    while True:
        schedule.run_pending()
        time.sleep(60)

if __name__ == "__main__":
    print("Data Harvester Service Starting...", flush=True)
    # Wait for DB to be ready (rudimentary check or just sleep)
    time.sleep(10)
    start_scheduler()
