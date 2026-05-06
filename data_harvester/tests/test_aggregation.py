"""Unit tests for the harvester aggregation step.

The aggregation logic was extracted into ``aggregate_chunk_to_long`` so we
can verify the per-nationality + TOTAL bookkeeping without spinning up a
database. These tests cover the invariants that matter at runtime: the
TOTAL row equals the sum of nationalities, sex/age duplication is
collapsed, and date columns are filtered to YYYY-MM strings only.
"""

from __future__ import annotations

import pandas as pd
import pytest

from data_harvester.harvester_tsv import aggregate_chunk_to_long


def _wide_chunk(rows):
    """Build a wide-format chunk like the one the chunk processor receives.

    ``rows`` is a list of (geo, citizen, *date_values) tuples; the date
    columns are inferred from the first row.
    """
    if not rows:
        return pd.DataFrame(columns=["geo", "citizen", "applicant"]), []
    n_dates = len(rows[0]) - 2
    date_cols = [f"2024-{m:02d}" for m in range(1, n_dates + 1)]
    data = []
    for geo, citizen, *values in rows:
        data.append([geo, citizen, "FRST", *values])
    df = pd.DataFrame(data, columns=["geo", "citizen", "applicant", *date_cols])
    return df, date_cols


def test_aggregate_emits_total_equal_to_sum_of_nationalities():
    df, date_cols = _wide_chunk(
        [
            ("FR", "SY", 100, 200),
            ("FR", "AF", 50, 70),
            ("DE", "SY", 80, 60),
        ]
    )
    out = aggregate_chunk_to_long(df, date_cols)

    # FR TOTAL for 2024-01 should be 100 + 50 = 150
    fr_total_jan = out.loc[
        (out["geo_code"] == "FR")
        & (out["citizen_code"] == "TOTAL")
        & (out["date"] == pd.Timestamp("2024-01-01")),
        "total_applications",
    ].iloc[0]
    assert fr_total_jan == 150

    # DE TOTAL for 2024-02 should be 60 (only one nationality)
    de_total_feb = out.loc[
        (out["geo_code"] == "DE")
        & (out["citizen_code"] == "TOTAL")
        & (out["date"] == pd.Timestamp("2024-02-01")),
        "total_applications",
    ].iloc[0]
    assert de_total_feb == 60


def test_aggregate_collapses_sex_age_duplication():
    """Multiple rows for the same (geo, citizen) — representing different
    sex/age combinations — must be summed into a single row per nationality."""
    df, date_cols = _wide_chunk(
        [
            ("FR", "SY", 10, 20),  # M, 18-34
            ("FR", "SY", 5, 8),    # F, 18-34
            ("FR", "SY", 3, 4),    # M, 35-64
        ]
    )
    out = aggregate_chunk_to_long(df, date_cols)

    fr_sy_jan = out.loc[
        (out["geo_code"] == "FR")
        & (out["citizen_code"] == "SY")
        & (out["date"] == pd.Timestamp("2024-01-01")),
        "total_applications",
    ]
    assert len(fr_sy_jan) == 1
    assert fr_sy_jan.iloc[0] == 18  # 10 + 5 + 3


def test_aggregate_drops_non_yyyy_mm_columns():
    df = pd.DataFrame(
        [
            ["FR", "SY", "FRST", 10, 20, 999],
        ],
        columns=["geo", "citizen", "applicant", "2024-01", "2024-02", "garbage"],
    )
    out = aggregate_chunk_to_long(df, ["2024-01", "2024-02", "garbage"])

    # No row should be emitted for the unparseable column.
    assert (out["date"].notna()).all()
    assert pd.Timestamp("2024-01-01") in out["date"].tolist()
    assert pd.Timestamp("2024-02-01") in out["date"].tolist()
    assert "garbage" not in out["date"].astype(str).tolist()


def test_aggregate_handles_empty_input():
    out = aggregate_chunk_to_long(pd.DataFrame(), ["2024-01"])
    assert out.empty
    assert list(out.columns) == [
        "date",
        "geo_code",
        "citizen_code",
        "applicant_type",
        "total_applications",
    ]


def test_aggregate_preserves_all_nationalities_per_geo():
    df, date_cols = _wide_chunk(
        [
            ("FR", "SY", 10),
            ("FR", "AF", 20),
            ("FR", "UA", 30),
            ("DE", "SY", 40),
        ]
    )
    out = aggregate_chunk_to_long(df, date_cols)

    fr_citizens = sorted(
        out.loc[(out["geo_code"] == "FR") & (out["citizen_code"] != "TOTAL"), "citizen_code"].unique()
    )
    assert fr_citizens == ["AF", "SY", "UA"]


def test_aggregate_total_invariant_holds_per_geo_per_date():
    """TOTAL = sum(per-nationality) for every (geo, date) combination."""
    df, date_cols = _wide_chunk(
        [
            ("FR", "SY", 100, 200),
            ("FR", "AF", 50, 70),
            ("FR", "UA", 25, 40),
            ("DE", "SY", 80, 60),
            ("DE", "AF", 12, 15),
        ]
    )
    out = aggregate_chunk_to_long(df, date_cols)

    for geo in ("FR", "DE"):
        per_cit = out[(out["geo_code"] == geo) & (out["citizen_code"] != "TOTAL")]
        totals = out[(out["geo_code"] == geo) & (out["citizen_code"] == "TOTAL")]
        for d in totals["date"].unique():
            expected = per_cit.loc[per_cit["date"] == d, "total_applications"].sum()
            actual = totals.loc[totals["date"] == d, "total_applications"].iloc[0]
            assert actual == expected, f"{geo} {d}: TOTAL={actual} ≠ sum={expected}"


def test_aggregate_applicant_type_is_frst_everywhere():
    df, date_cols = _wide_chunk([("FR", "SY", 10)])
    out = aggregate_chunk_to_long(df, date_cols)
    assert (out["applicant_type"] == "FRST").all()
