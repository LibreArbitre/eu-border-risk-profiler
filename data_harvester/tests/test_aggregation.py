"""Unit tests for the harvester's row selection, value parsing and reshaping.

These are the pure steps of the bulk-TSV pipeline, so they can be checked
without a database. They pin the rules that keep the stored figures equal
to what Eurostat publishes: only the all-sexes / all-ages row is counted,
the official TOTAL row is stored as is, and a cell that is not published
yet produces no row at all instead of a zero.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from data_harvester.harvester_tsv import aggregate_chunk_to_long, parse_values, select_rows

EU = {"FR", "DE"}


def _dimensions(rows):
    """Build the split-dimension frame the chunk processor works on."""
    return pd.DataFrame(rows, columns=["freq", "unit", "citizen", "sex", "applicant", "age", "geo"])


def _wide_chunk(rows):
    """Build a wide-format chunk like the one handed to the reshaping step.

    ``rows`` is a list of (geo, citizen, *date_values) tuples; the date
    columns are inferred from the first row.
    """
    if not rows:
        return pd.DataFrame(columns=["geo", "citizen", "applicant"]), []
    n_dates = len(rows[0]) - 2
    date_cols = [f"2024-{m:02d}" for m in range(1, n_dates + 1)]
    data = [[geo, citizen, "FRST", *values] for geo, citizen, *values in rows]
    df = pd.DataFrame(data, columns=["geo", "citizen", "applicant", *date_cols])
    return df, date_cols


def test_select_rows_keeps_only_the_all_sexes_all_ages_row():
    """The file carries T/M/F and TOTAL/age-band rows side by side; counting
    them all multiplies every applicant four to five times."""
    dims = _dimensions(
        [
            ("M", "PER", "SY", "T", "FRST", "TOTAL", "FR"),    # the real figure
            ("M", "PER", "SY", "M", "FRST", "TOTAL", "FR"),    # men only
            ("M", "PER", "SY", "F", "FRST", "TOTAL", "FR"),    # women only
            ("M", "PER", "SY", "T", "FRST", "Y18-34", "FR"),   # one age band
            ("M", "PER", "SY", "T", "FRST", "Y_LT18", "FR"),   # aggregate age band
            ("M", "PER", "SY", "UNK", "FRST", "UNK", "FR"),
        ]
    )
    assert select_rows(dims, EU).tolist() == [True, False, False, False, False, False]


def test_select_rows_filters_applicant_geo_and_citizenship():
    dims = _dimensions(
        [
            ("M", "PER", "SY", "T", "FRST", "TOTAL", "FR"),
            ("M", "PER", "TOTAL", "T", "FRST", "TOTAL", "FR"),      # official total: kept
            ("M", "PER", "SY", "T", "ASY_APP", "TOTAL", "FR"),      # not first-time
            ("M", "PER", "SY", "T", "FRST", "TOTAL", "CH"),         # not an EU member
            ("M", "PER", "EU27_2020", "T", "FRST", "TOTAL", "FR"),  # citizenship aggregate
            ("M", "PER", "STLS", "T", "FRST", "TOTAL", "FR"),       # stateless: in TOTAL only
        ]
    )
    assert select_rows(dims, EU).tolist() == [True, True, False, False, False, False]


def test_parse_values_keeps_missing_cells_missing():
    parsed = parse_values(pd.Series(["8665", "8665 p", ": ", ":", "0", " 15 "]))
    assert parsed.iloc[0] == 8665
    assert parsed.iloc[1] == 8665  # flags are stripped
    assert np.isnan(parsed.iloc[2])
    assert np.isnan(parsed.iloc[3])
    assert parsed.iloc[4] == 0  # a published zero stays a zero
    assert parsed.iloc[5] == 15


def test_aggregate_stores_the_official_total_untouched():
    """TOTAL comes from Eurostat (it includes stateless and unknown
    citizenships), so it is NOT the sum of the nationality rows."""
    df, date_cols = _wide_chunk(
        [
            ("FR", "SY", 100.0, 200.0),
            ("FR", "AF", 50.0, 70.0),
            ("FR", "TOTAL", 180.0, 300.0),
        ]
    )
    out = aggregate_chunk_to_long(df, date_cols)

    fr_total = out[(out["geo_code"] == "FR") & (out["citizen_code"] == "TOTAL")].sort_values("date")
    assert fr_total["total_applications"].tolist() == [180, 300]
    assert sorted(out["citizen_code"].unique()) == ["AF", "SY", "TOTAL"]


def test_aggregate_emits_no_row_for_unpublished_months():
    """A month a Member State has not reported yet must be absent, not 0."""
    df, date_cols = _wide_chunk(
        [
            ("DE", "TOTAL", 3135.0, np.nan),  # February not published yet
            ("FR", "TOTAL", 8665.0, 0.0),     # a genuine zero is still a value
        ]
    )
    out = aggregate_chunk_to_long(df, date_cols)

    de = out[out["geo_code"] == "DE"]
    assert de["date"].tolist() == [pd.Timestamp("2024-01-01")]
    assert de["total_applications"].tolist() == [3135]

    fr = out[out["geo_code"] == "FR"].sort_values("date")
    assert fr["total_applications"].tolist() == [8665, 0]


def test_aggregate_returns_integer_counts():
    df, date_cols = _wide_chunk([("FR", "SY", 10.0, 20.0)])
    out = aggregate_chunk_to_long(df, date_cols)
    assert pd.api.types.is_integer_dtype(out["total_applications"])


def test_aggregate_drops_non_yyyy_mm_columns():
    df = pd.DataFrame(
        [["FR", "SY", "FRST", 10.0, 20.0, 999.0]],
        columns=["geo", "citizen", "applicant", "2024-01", "2024-02", "garbage"],
    )
    out = aggregate_chunk_to_long(df, ["2024-01", "2024-02", "garbage"])

    assert out["date"].tolist() == [pd.Timestamp("2024-01-01"), pd.Timestamp("2024-02-01")]


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
            ("FR", "SY", 10.0),
            ("FR", "AF", 20.0),
            ("FR", "UA", 30.0),
            ("DE", "SY", 40.0),
        ]
    )
    out = aggregate_chunk_to_long(df, date_cols)

    assert sorted(out.loc[out["geo_code"] == "FR", "citizen_code"].unique()) == ["AF", "SY", "UA"]


def test_aggregate_applicant_type_is_frst_everywhere():
    df, date_cols = _wide_chunk([("FR", "SY", 10.0)])
    out = aggregate_chunk_to_long(df, date_cols)
    assert (out["applicant_type"] == "FRST").all()
