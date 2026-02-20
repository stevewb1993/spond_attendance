"""Tests for spond_attendance.transform module."""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from spond_attendance.transform import (
    _deduplicate,
    _extract_session_info,
    _parse_session_column,
    generate_outputs,
    merge_with_existing,
    transform_file,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Use dates well in the past to avoid future-session filtering in _deduplicate.
# Column headers are strings (as _parse_session_column handles) — this avoids
# a pandas 3.0 issue where melt() does not support raw datetime column keys.
SESSION_COL_A = "2024-03-09 14:00:00"
SESSION_COL_B = "2024-03-09 08:00:00"
SESSION_DATE = date(2024, 3, 9)


def _make_wide_df(
    members: list[str],
    sessions: dict[str, tuple[str, list]],
    *,
    include_disclaimer: bool = False,
) -> pd.DataFrame:
    """Build a synthetic wide-format DataFrame that mimics the Excel export.

    Parameters
    ----------
    members : list[str]
        Member names (one per data row).
    sessions : dict[str, tuple[str, list]]
        Mapping from session datetime *string* (used as column header) to
        (session_name_with_optional_star, [attendance values per member]).
    include_disclaimer : bool
        If True, append a disclaimer row at the bottom.

    The returned DataFrame has:
      - A "Name" column and an "Unnamed: 6" column (non-session filler).
      - One column per session keyed by a datetime string.
      - Row 0 contains session names (and NaN for non-session columns).
      - Rows 1..N contain member attendance data.
    """
    col_order = ["Name", "Unnamed: 6"] + list(sessions.keys())

    # Row 0: session-name row
    row0: dict = {"Name": np.nan, "Unnamed: 6": np.nan}
    for col, (sname, _vals) in sessions.items():
        row0[col] = sname

    # Data rows
    data_rows = []
    for i, name in enumerate(members):
        row: dict = {"Name": name, "Unnamed: 6": np.nan}
        for col, (_sname, vals) in sessions.items():
            row[col] = vals[i]
        data_rows.append(row)

    rows = [row0] + data_rows

    if include_disclaimer:
        disclaimer_row: dict = {
            "Name": "*Attendance has not been confirmed",
            "Unnamed: 6": np.nan,
        }
        for col in sessions:
            disclaimer_row[col] = np.nan
        rows.append(disclaimer_row)

    df = pd.DataFrame(rows, columns=col_order)  # ty: ignore[invalid-argument-type]
    return df


# ---------------------------------------------------------------------------
# _parse_session_column
# ---------------------------------------------------------------------------


class TestParseSessionColumn:
    def test_datetime_object_returns_itself(self):
        dt = datetime(2025, 4, 9, 18, 45)
        result = _parse_session_column(dt)
        assert result == dt
        assert isinstance(result, datetime)

    def test_pd_timestamp_returns_datetime(self):
        ts = pd.Timestamp("2025-04-09 18:45:00")
        result = _parse_session_column(ts)
        assert result == datetime(2025, 4, 9, 18, 45)
        assert isinstance(result, datetime)

    def test_string_with_pandas_suffix_parses_correctly(self):
        result = _parse_session_column("2025-04-09 18:45:00.1")
        assert result == datetime(2025, 4, 9, 18, 45)

    def test_normal_datetime_string_parses_correctly(self):
        result = _parse_session_column("2025-04-09 18:45:00")
        assert result == datetime(2025, 4, 9, 18, 45)

    def test_non_datetime_string_returns_none(self):
        assert _parse_session_column("Name") is None

    def test_integer_returns_none(self):
        assert _parse_session_column(42) is None


# ---------------------------------------------------------------------------
# _extract_session_info
# ---------------------------------------------------------------------------


class TestExtractSessionInfo:
    def test_extracts_sessions_from_synthetic_df(self):
        dt_a = datetime(2025, 4, 12, 14, 0)
        dt_b = datetime(2025, 4, 12, 8, 0)
        df = pd.DataFrame(
            {
                "Name": [np.nan, "Alice"],
                "Unnamed: 6": [np.nan, np.nan],
                dt_a: ["Session A*", 1],
                dt_b: ["Session B*", np.nan],
            }
        )
        info = _extract_session_info(df)

        # Two session columns found
        assert len(info) == 2

        # Stars stripped from session names
        assert info[dt_a] == ("Session A", date(2025, 4, 12))  # ty: ignore[invalid-argument-type]
        assert info[dt_b] == ("Session B", date(2025, 4, 12))  # ty: ignore[invalid-argument-type]

    def test_non_datetime_columns_ignored(self):
        dt = datetime(2025, 4, 12, 14, 0)
        df = pd.DataFrame(
            {
                "Name": [np.nan, "Alice"],
                "SomeOtherCol": [np.nan, "x"],
                dt: ["Training*", 1],
            }
        )
        info = _extract_session_info(df)
        assert len(info) == 1
        assert dt in info


# ---------------------------------------------------------------------------
# transform_file
# ---------------------------------------------------------------------------


class TestTransformFile:
    def test_basic_shape_and_columns(self):
        members = ["Alice", "Bob", "Charlie"]
        sessions = {
            SESSION_COL_A: ("Session A*", [1, np.nan, 1]),
            SESSION_COL_B: ("Session B*", [np.nan, 1, 1]),
        }
        df = _make_wide_df(members, sessions)
        result = transform_file(df)

        # 3 members x 2 sessions = 6 rows
        assert result.shape[0] == 6

        expected_cols = [
            "name",
            "session_name",
            "session_date",
            "session_day_of_week",
            "attended",
        ]
        assert list(result.columns) == expected_cols

    def test_attended_is_int_nan_becomes_zero(self):
        members = ["Alice"]
        sessions = {
            SESSION_COL_A: ("Session A*", [1]),
            SESSION_COL_B: ("Session B*", [np.nan]),
        }
        df = _make_wide_df(members, sessions)
        result = transform_file(df)

        attended_values = sorted(result["attended"].tolist())
        assert attended_values == [0, 1]
        assert result["attended"].dtype == int

    def test_disclaimer_row_filtered_out(self):
        members = ["Alice", "Bob"]
        sessions = {
            SESSION_COL_A: ("Session A*", [1, 1]),
        }
        df = _make_wide_df(members, sessions, include_disclaimer=True)
        result = transform_file(df)

        # Only Alice and Bob, not the disclaimer row
        assert set(result["name"].unique()) == {"Alice", "Bob"}
        assert result.shape[0] == 2

    def test_row_zero_not_included_as_data(self):
        """Row 0 contains session names, not attendance data.
        It should never appear as a member row in the output."""
        members = ["Alice"]
        sessions = {
            SESSION_COL_A: ("Training*", [1]),
        }
        df = _make_wide_df(members, sessions)
        result = transform_file(df)

        # Only Alice should be present, not NaN or any session-name text
        assert list(result["name"].unique()) == ["Alice"]

    def test_session_day_of_week_correct(self):
        # 2024-03-09 is a Saturday
        members = ["Alice"]
        sessions = {
            SESSION_COL_A: ("Session A*", [1]),
        }
        df = _make_wide_df(members, sessions)
        result = transform_file(df)

        assert result["session_day_of_week"].iloc[0] == "Saturday"

    def test_raises_when_no_session_columns(self):
        df = pd.DataFrame({"Name": ["Alice", "Bob"], "SomeCol": [1, 2]})
        with pytest.raises(ValueError, match="No session columns found"):
            transform_file(df)


# ---------------------------------------------------------------------------
# merge_with_existing / _deduplicate
# ---------------------------------------------------------------------------


class TestMergeWithExisting:
    def _make_long_row(self, name, session_name, session_date, attended):
        return {
            "name": name,
            "session_name": session_name,
            "session_date": session_date,
            "session_day_of_week": session_date.strftime("%A"),
            "attended": attended,
        }

    def test_existing_wins_over_new_for_same_key(self):
        existing = pd.DataFrame(
            [self._make_long_row("Alice", "Training", date(2024, 1, 10), 1)]
        )
        new = pd.DataFrame(
            [self._make_long_row("Alice", "Training", date(2024, 1, 10), 0)]
        )
        result = merge_with_existing(existing, new)

        assert len(result) == 1
        assert result.iloc[0]["attended"] == 1  # existing value wins

    def test_new_data_fills_in_missing_rows(self):
        existing = pd.DataFrame(
            [self._make_long_row("Alice", "Training", date(2024, 1, 10), 1)]
        )
        new = pd.DataFrame(
            [
                self._make_long_row("Alice", "Training", date(2024, 1, 10), 0),
                self._make_long_row("Bob", "Training", date(2024, 1, 10), 1),
            ]
        )
        result = merge_with_existing(existing, new)

        assert len(result) == 2
        names = set(result["name"])
        assert names == {"Alice", "Bob"}
        # Alice keeps her existing value
        alice_row = result[result["name"] == "Alice"].iloc[0]
        assert alice_row["attended"] == 1

    def test_future_sessions_filtered_out(self):
        existing = pd.DataFrame(
            [
                self._make_long_row("Alice", "Training", date(2024, 1, 10), 1),
                self._make_long_row("Alice", "Training", date(2099, 12, 31), 1),
            ]
        )
        new = pd.DataFrame(
            [self._make_long_row("Bob", "Training", date(2099, 12, 31), 1)]
        )
        result = merge_with_existing(existing, new)

        # Only the 2024 row survives; both 2099 rows are filtered out
        assert len(result) == 1
        assert result.iloc[0]["name"] == "Alice"
        assert result.iloc[0]["session_date"] == date(2024, 1, 10)


class TestDeduplicate:
    def test_keeps_lowest_source_rank(self):
        df = pd.DataFrame(
            [
                {
                    "name": "Alice",
                    "session_name": "Training",
                    "session_date": date(2024, 1, 10),
                    "session_day_of_week": "Wednesday",
                    "attended": 1,
                    "_source_rank": 0,
                },
                {
                    "name": "Alice",
                    "session_name": "Training",
                    "session_date": date(2024, 1, 10),
                    "session_day_of_week": "Wednesday",
                    "attended": 0,
                    "_source_rank": 1,
                },
            ]
        )
        result = _deduplicate(df)
        assert len(result) == 1
        assert result.iloc[0]["attended"] == 1

    def test_result_sorted_by_date_session_name(self):
        df = pd.DataFrame(
            [
                {
                    "name": "Bob",
                    "session_name": "Training",
                    "session_date": date(2024, 2, 1),
                    "session_day_of_week": "Thursday",
                    "attended": 1,
                    "_source_rank": 0,
                },
                {
                    "name": "Alice",
                    "session_name": "Training",
                    "session_date": date(2024, 1, 10),
                    "session_day_of_week": "Wednesday",
                    "attended": 1,
                    "_source_rank": 0,
                },
            ]
        )
        result = _deduplicate(df)
        assert list(result["name"]) == ["Alice", "Bob"]


# ---------------------------------------------------------------------------
# generate_outputs
# ---------------------------------------------------------------------------


class TestGenerateOutputs:
    def test_writes_two_csv_files(self, tmp_path: Path):
        df = pd.DataFrame(
            [
                {
                    "name": "Alice",
                    "session_name": "Training",
                    "session_date": date(2024, 1, 10),
                    "session_day_of_week": "Wednesday",
                    "attended": 1,
                },
                {
                    "name": "Bob",
                    "session_name": "Training",
                    "session_date": date(2024, 1, 10),
                    "session_day_of_week": "Wednesday",
                    "attended": 1,
                },
                {
                    "name": "Alice",
                    "session_name": "Match",
                    "session_date": date(2024, 1, 12),
                    "session_day_of_week": "Friday",
                    "attended": 0,
                },
            ]
        )
        detail_path, summary_path = generate_outputs(df, tmp_path / "out")

        assert detail_path.exists()
        assert summary_path.exists()
        assert detail_path.name == "spond.csv"
        assert summary_path.name == "session_attendance.csv"

    def test_uses_pipe_separator(self, tmp_path: Path):
        df = pd.DataFrame(
            [
                {
                    "name": "Alice",
                    "session_name": "Training",
                    "session_date": date(2024, 1, 10),
                    "session_day_of_week": "Wednesday",
                    "attended": 1,
                },
            ]
        )
        detail_path, summary_path = generate_outputs(df, tmp_path / "out")

        detail_content = detail_path.read_text()
        assert "|" in detail_content
        # Pipe should be the separator; commas should not appear as separators
        detail_lines = detail_content.strip().splitlines()
        assert (
            detail_lines[0]
            == "name|session_name|session_date|session_day_of_week|attended"
        )

        summary_content = summary_path.read_text()
        summary_lines = summary_content.strip().splitlines()
        assert (
            summary_lines[0] == "session_name|session_date|session_day_of_week|attended"
        )

    def test_session_attendance_aggregation(self, tmp_path: Path):
        df = pd.DataFrame(
            [
                {
                    "name": "Alice",
                    "session_name": "Training",
                    "session_date": date(2024, 1, 10),
                    "session_day_of_week": "Wednesday",
                    "attended": 1,
                },
                {
                    "name": "Bob",
                    "session_name": "Training",
                    "session_date": date(2024, 1, 10),
                    "session_day_of_week": "Wednesday",
                    "attended": 1,
                },
                {
                    "name": "Charlie",
                    "session_name": "Training",
                    "session_date": date(2024, 1, 10),
                    "session_day_of_week": "Wednesday",
                    "attended": 0,
                },
                {
                    "name": "Alice",
                    "session_name": "Match",
                    "session_date": date(2024, 1, 12),
                    "session_day_of_week": "Friday",
                    "attended": 1,
                },
            ]
        )
        _detail_path, summary_path = generate_outputs(df, tmp_path / "out")

        summary = pd.read_csv(summary_path, sep="|")
        assert len(summary) == 2

        training_row = summary[summary["session_name"] == "Training"].iloc[0]
        assert training_row["attended"] == 2  # Alice + Bob

        match_row = summary[summary["session_name"] == "Match"].iloc[0]
        assert match_row["attended"] == 1  # Alice only

    def test_creates_output_directory(self, tmp_path: Path):
        df = pd.DataFrame(
            [
                {
                    "name": "Alice",
                    "session_name": "Training",
                    "session_date": date(2024, 1, 10),
                    "session_day_of_week": "Wednesday",
                    "attended": 1,
                },
            ]
        )
        nested = tmp_path / "a" / "b" / "c"
        assert not nested.exists()
        generate_outputs(df, nested)
        assert nested.exists()
