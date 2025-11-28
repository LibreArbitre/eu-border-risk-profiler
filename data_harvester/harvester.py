import argparse
import logging
import os
import sys
import time
from datetime import datetime, timedelta
from typing import Dict, Iterable, List

import pandas as pd
import requests
from requests import HTTPError
import schedule
from sqlalchemy import column, create_engine, table
from sqlalchemy.dialects.postgresql import insert

DB_USER = os.getenv("DB_USER", "user")
DB_PASSWORD = os.getenv("DB_PASSWORD", "password")
DB_NAME = os.getenv("DB_NAME", "eubrp_db")
DB_HOST = os.getenv("DB_HOST", "db")
DB_PORT = os.getenv("DB_PORT", "5432")

RETRY_MAX_ATTEMPTS = int(os.getenv("RETRY_MAX_ATTEMPTS", "3"))
RETRY_BACKOFF_SECONDS = float(os.getenv("RETRY_BACKOFF_SECONDS", "2"))
EXIT_ON_FAILURE = os.getenv("EXIT_ON_FAILURE", "true").lower() == "true"
HEALTH_FILE = os.getenv("HARVESTER_HEALTH_FILE", "/tmp/harvester_health")
MONTHS_TO_FETCH = int(os.getenv("HARVESTER_MONTHS", "60"))
TIME_CHUNK_SIZE = int(os.getenv("HARVESTER_TIME_CHUNK", "12"))
HARVESTER_LAG_MONTHS = int(os.getenv("HARVESTER_LAG_MONTHS", "2"))

DATABASE_URL = f"postgresql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"

BASE_URL = "https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/migr_asyappctzm"
EU_COUNTRIES = [
    "AT",
    "BE",
    "BG",
    "HR",
    "CY",
    "CZ",
    "DK",
    "EE",
    "FI",
    "FR",
    "DE",
    "EL",
    "HU",
    "IE",
    "IT",
    "LV",
    "LT",
    "LU",
    "MT",
    "NL",
    "PL",
    "PT",
    "RO",
    "SK",
    "SI",
    "ES",
    "SE",
]


def configure_logging() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")


def retry(operation_name: str):
    def decorator(func):
        def wrapper(*args, **kwargs):
            delay = RETRY_BACKOFF_SECONDS
            for attempt in range(1, RETRY_MAX_ATTEMPTS + 1):
                try:
                    return func(*args, **kwargs)
                except Exception as exc:  # noqa: PERF203 acceptable for logging
                    if isinstance(exc, HTTPError) and exc.response is not None:
                        if exc.response.status_code == 400:
                            raise
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


def build_time_periods(months: int) -> List[str]:
    end_date = first_day_n_months_ago(HARVESTER_LAG_MONTHS)
    start_date = end_date - timedelta(days=months * 30)
    periods = []
    current = end_date
    while current >= start_date:
        periods.append(f"{current.year}M{current.month:02d}")
        current -= timedelta(days=30)
    return sorted(set(periods))


def first_day_n_months_ago(months_ago: int) -> datetime:
    """Return the first day UTC of the month that is ``months_ago`` in the past.

    This avoids querying months that are still in progress or not yet published
    by Eurostat (which respond with HTTP 400), preventing the harvester from
    repeatedly hitting unavailable future months.
    """

    now = datetime.utcnow()
    year = now.year
    month = now.month

    for _ in range(months_ago):
        month -= 1
        if month == 0:
            month = 12
            year -= 1

    return datetime(year, month, 1)


def chunk_iterable(items: Iterable[str], size: int) -> Iterable[List[str]]:
    chunk: List[str] = []
    for item in items:
        chunk.append(item)
        if len(chunk) == size:
            yield chunk
            chunk = []
    if chunk:
        yield chunk


def fetch_country_time_chunk(country: str, times: List[str]) -> List[Dict]:
    try:
        return [fetch_country_period(country, times)]
    except HTTPError as exc:
        status = exc.response.status_code if exc.response is not None else None
        if status == 400 and len(times) > 1:
            mid = len(times) // 2
            left = times[:mid]
            right = times[mid:]
            logging.info(
                "Splitting time chunk for %s after HTTP 400 into %s and %s",
                country,
                ",".join(left),
                ",".join(right),
            )
            payloads: List[Dict] = []
            payloads.extend(fetch_country_time_chunk(country, left))
            payloads.extend(fetch_country_time_chunk(country, right))
            return payloads
        if status == 400 and len(times) == 1:
            logging.warning(
                "Dropping period %s for %s after HTTP 400", times[0], country
            )
            return []
        raise


@retry("Eurostat fetch")
def fetch_country_period(country: str, times: List[str]) -> Dict:
    params = {
        "format": "JSON",
        "lang": "en",
        "geo": country,
        "time": ",".join(times),
    }
    logging.info("Fetching %s for periods %s", country, ",".join(times))
    response = requests.get(BASE_URL, params=params, timeout=60)
    response.raise_for_status()
    return response.json()


def fetch_eurostat_data() -> List[Dict]:
    time_periods = list(build_time_periods(MONTHS_TO_FETCH))
    all_payloads: List[Dict] = []

    for country in EU_COUNTRIES:
        for time_chunk in chunk_iterable(time_periods, TIME_CHUNK_SIZE):
            try:
                payloads = fetch_country_time_chunk(country, time_chunk)
            except Exception as exc:  # noqa: PERF203 logging
                logging.warning(
                    "Skipping chunk for %s (%s): %s", country, ",".join(time_chunk), exc
                )
                continue

            for payload in payloads:
                if payload and payload.get("value"):
                    all_payloads.append(payload)
                else:
                    logging.info("No data returned for %s (%s)", country, ",".join(time_chunk))

    if not all_payloads:
        logging.warning("No data fetched from Eurostat; continuing without updates")
    else:
        logging.info("Fetched %s payloads from Eurostat", len(all_payloads))
    return all_payloads


def parse_eurostat_json(payloads: List[Dict]) -> pd.DataFrame:
    if not payloads:
        return pd.DataFrame()

    records = []
    for payload in payloads:
        if not payload or "value" not in payload or "dimension" not in payload:
            continue

        dims = payload["dimension"]
        ids = payload.get("id", [])
        values = payload.get("value", {})

        dimensions_map: Dict[str, Dict[int, str]] = {}
        sizes: List[int] = []
        for dim_id in ids:
            dim_info = dims[dim_id]
            idx_map = dim_info["category"]["index"]
            inv_map = {int(v): k for k, v in idx_map.items()}
            dimensions_map[dim_id] = inv_map
            sizes.append(len(inv_map))

        strides = [1] * len(sizes)
        for i in range(len(sizes) - 2, -1, -1):
            strides[i] = strides[i + 1] * sizes[i + 1]

        for raw_index, value in values.items():
            idx = int(raw_index)
            coords: Dict[str, str] = {}
            for i, dim_id in enumerate(ids):
                pos = (idx // strides[i]) % sizes[i]
                coords[dim_id] = dimensions_map[dim_id][pos]

            time_label = coords.get("time")
            geo = coords.get("geo")
            citizen = coords.get("citizen")
            applicant = coords.get("applicant")

            if time_label and "M" in time_label:
                year, month = time_label.split("M")
                date_str = f"{year}-{month:0>2}-01"
            else:
                continue

            records.append(
                {
                    "date": date_str,
                    "geo_code": geo,
                    "citizen_code": citizen,
                    "applicant_type": applicant,
                    "total_applications": value,
                }
            )

    return pd.DataFrame(records)


def clean_data(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df

    if "applicant_type" in df.columns:
        df = df[df["applicant_type"] == "FRST"].copy()
    if "citizen_code" in df.columns:
        df = df[df["citizen_code"] == "TOTAL"].copy()

    df["total_applications"] = pd.to_numeric(df["total_applications"], errors="coerce").fillna(0).astype(int)
    df.dropna(subset=["date", "geo_code"], inplace=True)
    df.drop_duplicates(subset=["date", "geo_code", "citizen_code", "applicant_type"], inplace=True)
    return df


@retry("DB save")
def save_to_db(df: pd.DataFrame) -> None:
    if df.empty:
        logging.info("No data to save.")
        return

    engine = get_db_engine()
    asylum_table = table(
        "asylum_data",
        column("date"),
        column("geo_code"),
        column("citizen_code"),
        column("applicant_type"),
        column("total_applications"),
    )

    records = df.to_dict(orient="records")
    chunk_size = 2000

    logging.info("Saving %s records to DB...", len(records))
    with engine.begin() as conn:
        for start in range(0, len(records), chunk_size):
            chunk = records[start : start + chunk_size]
            stmt = insert(asylum_table).values(chunk)
            stmt = stmt.on_conflict_do_update(
                index_elements=["date", "geo_code", "citizen_code", "applicant_type"],
                set_={"total_applications": stmt.excluded.total_applications},
            )
            conn.execute(stmt)
    logging.info("Data saved successfully.")


def write_health(status: bool, message: str = "") -> None:
    payload = {
        "status": "healthy" if status else "unhealthy",
        "timestamp": datetime.utcnow().isoformat(),
        "message": message,
    }
    try:
        with open(HEALTH_FILE, "w", encoding="utf-8") as health_file:
            health_file.write(str(payload))
    except Exception:  # noqa: PERF203 logging
        logging.exception("Failed to write health status")


def check_health() -> bool:
    try:
        with open(HEALTH_FILE, "r", encoding="utf-8") as health_file:
            data = health_file.read()
            return "healthy" in data
    except FileNotFoundError:
        logging.error("Health file not found at %s", HEALTH_FILE)
    except Exception:  # noqa: PERF203 logging
        logging.exception("Error reading health file")
    return False


def run_harvest() -> None:
    logging.info("--- Starting Eurostat Harvest Job ---")
    success = True
    message = ""

    try:
        payloads = fetch_eurostat_data()
        df = parse_eurostat_json(payloads)
        logging.info("Parsed %s raw records", len(df))
        df = clean_data(df)
        logging.info("Filtered down to %s records after cleaning", len(df))
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


def start_scheduler() -> None:
    run_harvest()
    schedule.every().day.at("02:00").do(run_harvest)

    logging.info("Scheduler started. Waiting for jobs...")
    while True:
        schedule.run_pending()
        time.sleep(60)


def main() -> None:
    parser = argparse.ArgumentParser(description="Data harvester service")
    parser.add_argument("--healthcheck", action="store_true", help="Run healthcheck and exit")
    args = parser.parse_args()

    configure_logging()

    if args.healthcheck:
        sys.exit(0 if check_health() else 1)

    logging.info("Data Harvester Service Starting...")
    time.sleep(5)
    start_scheduler()


if __name__ == "__main__":
    main()
