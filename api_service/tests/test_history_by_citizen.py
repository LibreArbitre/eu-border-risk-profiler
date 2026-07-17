"""Integration test for the per-nationality history endpoint.

Spins up an in-memory SQLite database, populates it with a small fixture
that mirrors the harvester's output (per-nationality rows + a TOTAL row
per (date, geo)), then exercises the endpoint to verify ordering,
filtering and the top-N ranking.
"""

from __future__ import annotations

import importlib
import sys
from datetime import datetime

import pytest
from sqlalchemy import create_engine, text

SCHEMA_SQL = """
CREATE TABLE asylum_data (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date DATE NOT NULL,
    geo_code VARCHAR(10) NOT NULL,
    citizen_code VARCHAR(10) NOT NULL,
    applicant_type VARCHAR(50) NOT NULL,
    total_applications INTEGER,
    extraction_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""


@pytest.fixture()
def app_module(tmp_path, monkeypatch):
    db_url = f"sqlite:///{tmp_path/'history_test.db'}"
    for key, value in {
        "DB_USER": "user",
        "DB_PASSWORD": "pw",
        "DB_NAME": "db",
        "DB_HOST": "host",
        "DB_PORT": "5432",
    }.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv("DATABASE_URL", db_url)

    sys.modules.pop("api_service.main", None)
    main = importlib.import_module("api_service.main")

    engine = create_engine(db_url)
    with engine.begin() as conn:
        conn.execute(text(SCHEMA_SQL))
    main.engine = engine
    yield main


def _seed(engine, rows):
    insert_sql = text(
        """
        INSERT INTO asylum_data
            (date, geo_code, citizen_code, applicant_type, total_applications)
        VALUES (:date, :geo_code, :citizen_code, :applicant_type, :total_applications)
        """
    )
    with engine.begin() as conn:
        for row in rows:
            conn.execute(insert_sql, row)


def _row(date, citizen_code, total, geo_code="FR"):
    """Build one asylum_data fixture row (FRST applicant type)."""
    return {
        "date": date,
        "geo_code": geo_code,
        "citizen_code": citizen_code,
        "applicant_type": "FRST",
        "total_applications": total,
    }


def test_top_n_ranks_by_volume_and_excludes_total(app_module):
    _seed(
        app_module.engine,
        [
            # SY=300, AF=210, UA=150, TR=100, IQ=40 — top 3 should be SY, AF, UA
            _row(datetime(2024, 1, 1), "SY", 200),
            _row(datetime(2024, 2, 1), "SY", 100),
            _row(datetime(2024, 1, 1), "AF", 120),
            _row(datetime(2024, 2, 1), "AF", 90),
            _row(datetime(2024, 1, 1), "UA", 100),
            _row(datetime(2024, 2, 1), "UA", 50),
            _row(datetime(2024, 1, 1), "TR", 100),
            _row(datetime(2024, 1, 1), "IQ", 40),
            # Pre-aggregated TOTAL row that must NOT show up in the breakdown
            _row(datetime(2024, 1, 1), "TOTAL", 560),
            _row(datetime(2024, 2, 1), "TOTAL", 240),
        ],
    )

    results = app_module.get_history_by_citizen(geo_code="FR", top=3, since=None)
    citizens = sorted({r["citizen_code"] for r in results})

    assert citizens == ["AF", "SY", "UA"]
    assert "TOTAL" not in citizens
    # Two months × 3 nationalities = 6 rows
    assert len(results) == 6


def test_returns_404_for_unknown_geo(app_module):
    _seed(
        app_module.engine,
        [
            _row(datetime(2024, 1, 1), "SY", 100),
        ],
    )
    with pytest.raises(app_module.HTTPException) as excinfo:
        app_module.get_history_by_citizen(geo_code="XX", top=5, since=None)
    assert excinfo.value.status_code == 404


def test_since_parameter_clamps_history(app_module):
    _seed(
        app_module.engine,
        [
            _row(datetime(2023, 1, 1), "SY", 50),
            _row(datetime(2024, 6, 1), "SY", 100),
        ],
    )
    results = app_module.get_history_by_citizen(geo_code="FR", top=5, since="2024-01-01")
    # Only the 2024 row should remain.
    assert len(results) == 1
    assert results[0]["citizen_code"] == "SY"
    assert results[0]["total"] == 100
