"""Tests for spond_attendance.summary module."""

import pandas as pd
import pytest

from spond_attendance.summary import (
    html_table,
    load_attendance,
    month_window,
    yoy_summary,
)


@pytest.fixture
def data_dir(tmp_path):
    rows = [
        # Monday and Saturday swims, a year apart, plus a bike session
        ("STV Swim", "2025-09-01", "Monday", 10),
        ("STV Swim", "2025-09-08", "Monday", 12),
        ("STV Swim", "2026-09-07", "Monday", 14),
        ("STV Swim", "2026-09-14", "Monday", 16),
        ("STV Swim", "2026-10-05", "Monday", 13),
        ("STV Swim", "2026-10-03", "Saturday", 20),
        ("Indoor Bike", "2026-10-06", "Tuesday", 8),
        # A session that stopped running before the window
        ("S&C", "2025-10-07", "Tuesday", 5),
    ]
    attendance = pd.DataFrame(
        rows,
        columns=pd.Index(
            ["session_name", "session_date", "session_day_of_week", "attended"]
        ),
    )
    attendance.to_csv(tmp_path / "session_attendance.csv", sep="|", index=False)
    pd.DataFrame(
        {
            "session_name": ["STV Swim", "Indoor Bike", "S&C"],
            "category": ["Swim", "Bike", "S&C"],
        }
    ).to_csv(tmp_path / "session_types.csv", index=False)
    return tmp_path


def test_month_window_crosses_year_boundary():
    assert month_window((2026, 2), 3) == [(2025, 12), (2026, 1), (2026, 2)]


def test_summary_rows_cells_and_ordering(data_dir):
    df = load_attendance(data_dir)
    summary = yoy_summary(df, df, ["STV Swim", "Indoor Bike", "S&C"], num_months=2)

    assert summary is not None
    assert summary.col_headers == ["Sep 2026", "Oct 2026"]
    # Swim before Bike, Monday before Saturday; Tuesday S&C has no current data
    assert summary.row_labels == [
        "── Swim ──",
        "STV Swim (Mon)",
        "STV Swim (Sat)",
        "── Bike ──",
        "Indoor Bike (Tue)",
    ]
    assert summary.row_data["Sep 2026"] == ["", "15.0  (+4.0)", "—", "", "—"]
    assert summary.row_data["Oct 2026"] == ["", "13.0", "20.0", "", "8.0"]


def test_end_month_overrides_latest(data_dir):
    df = load_attendance(data_dir)
    summary = yoy_summary(df, df, ["STV Swim"], num_months=1, end=(2026, 9))

    assert summary is not None
    assert summary.col_headers == ["Sep 2026"]
    assert summary.row_labels == ["── Swim ──", "STV Swim (Mon)"]


def test_prior_year_comes_from_full_data(data_dir):
    df = load_attendance(data_dir)
    current = df[df["year"] == 2026]
    summary = yoy_summary(current, df, ["STV Swim"], num_months=2)

    assert summary is not None
    assert summary.row_data["Sep 2026"][1] == "15.0  (+4.0)"


def test_no_data_returns_none(data_dir):
    df = load_attendance(data_dir)
    assert yoy_summary(df, df, ["Not a session"]) is None


def test_html_table_colours_changes(data_dir):
    df = load_attendance(data_dir)
    summary = yoy_summary(df, df, ["STV Swim"], num_months=2)

    assert summary is not None
    html = html_table(summary)
    assert html.startswith("<table")
    assert '15.0 <span style="color:#2e7d32;font-size:11px">(+4.0)</span>' in html
    assert "── Swim ──" in html
