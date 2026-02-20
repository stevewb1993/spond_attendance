"""Integration tests using real Spond xlsx files."""

from __future__ import annotations

import shutil
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from spond_attendance import io, transform
from spond_attendance.cli import main

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

data_dir_exists = pytest.mark.skipif(
    not DATA_DIR.is_dir(),
    reason=f"Real data directory {DATA_DIR} not found",
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def single_file(tmp_path: Path) -> Path:
    """Copy a single xlsx file to a temp directory and return the file path."""
    src = DATA_DIR / "spond_attendance_apr_25.xlsx"
    dst = tmp_path / src.name
    shutil.copy(src, dst)
    return dst


@pytest.fixture()
def two_files(tmp_path: Path) -> Path:
    """Copy two chronologically adjacent xlsx files to a temp directory."""
    names = [
        "spond_attendance_mar_24.xlsx",
        "spond_attendance_apr_24.xlsx",
    ]
    for name in names:
        shutil.copy(DATA_DIR / name, tmp_path / name)
    return tmp_path


@pytest.fixture()
def three_files(tmp_path: Path) -> Path:
    """Copy three xlsx files to a temp directory."""
    names = [
        "spond_attendance_mar_24.xlsx",
        "spond_attendance_apr_24.xlsx",
        "spond_attendance_may_25.xlsx",
    ]
    for name in names:
        shutil.copy(DATA_DIR / name, tmp_path / name)
    return tmp_path


# ---------------------------------------------------------------------------
# test_single_file_processing
# ---------------------------------------------------------------------------


@data_dir_exists
class TestSingleFileProcessing:
    """Process one real xlsx file and verify the transformed output."""

    def test_output_has_expected_columns(self, single_file: Path):
        df = io.read_attendance_file(single_file)
        result = transform.transform_file(df)
        assert list(result.columns) == [
            "name",
            "session_name",
            "session_date",
            "session_day_of_week",
            "attended",
        ]

    def test_no_nan_in_name(self, single_file: Path):
        df = io.read_attendance_file(single_file)
        result = transform.transform_file(df)
        assert result["name"].notna().all(), "Found NaN values in name column"

    def test_no_disclaimer_rows(self, single_file: Path):
        df = io.read_attendance_file(single_file)
        result = transform.transform_file(df)
        disclaimer_mask = result["name"].astype(str).str.startswith("*Attendance")
        assert not disclaimer_mask.any(), "Found disclaimer rows in output"

    def test_attended_values_only_zero_or_one(self, single_file: Path):
        df = io.read_attendance_file(single_file)
        result = transform.transform_file(df)
        assert set(result["attended"].unique()).issubset({0, 1})

    def test_session_dates_are_date_objects_in_the_past(self, single_file: Path):
        df = io.read_attendance_file(single_file)
        result = transform.transform_file(df)
        today = date.today()
        for d in result["session_date"]:
            assert isinstance(d, date), f"Expected date object, got {type(d)}"
            assert d < today, f"Session date {d} is not in the past"

    def test_reasonable_row_count(self, single_file: Path):
        df = io.read_attendance_file(single_file)
        result = transform.transform_file(df)
        assert len(result) > 1000, (
            f"Expected > 1000 rows from a real file, got {len(result)}"
        )

    def test_session_names_do_not_end_with_asterisk(self, single_file: Path):
        df = io.read_attendance_file(single_file)
        result = transform.transform_file(df)
        trailing_star = result["session_name"].str.endswith("*")
        assert not trailing_star.any(), (
            "Found session names ending with '*' — they should be stripped"
        )


# ---------------------------------------------------------------------------
# test_attendance_figures (spond_attendance_apr_25.xlsx)
# ---------------------------------------------------------------------------


@data_dir_exists
class TestAttendanceFigures:
    """Verify attendance figures match expected values from the raw Excel."""

    @pytest.fixture(autouse=True)
    def _load(self, single_file: Path):
        df = io.read_attendance_file(single_file)
        self.result = transform.transform_file(df)

    def test_total_rows(self):
        assert len(self.result) == 33674

    def test_unique_members(self):
        assert self.result["name"].nunique() == 113

    def test_unique_sessions(self):
        sessions = self.result.groupby(["session_name", "session_date"]).ngroups
        assert sessions == 298

    def test_total_attended(self):
        assert self.result["attended"].sum() == 2543

    def test_every_member_has_all_sessions(self):
        """Each member should have exactly one row per session."""
        per_member = self.result.groupby("name").size()
        assert (per_member == 298).all()

    def test_stv_swim_apr_12_attendance_count(self):
        session = self.result[
            (self.result["session_name"] == "STV Swim")
            & (self.result["session_date"] == date(2025, 4, 12))
        ]
        assert session["attended"].sum() == 13

    def test_stv_swim_apr_12_specific_attendees(self):
        session = self.result[
            (self.result["session_name"] == "STV Swim")
            & (self.result["session_date"] == date(2025, 4, 12))
            & (self.result["attended"] == 1)
        ]
        actual = set(session["name"])
        expected = {
            "Andy Reid",
            "Ben Williams",
            "Carole Jenkins",
            "Elizabeth Cowley",
            "Emma Sewart",
            "Graham Oak",
            "Jamie Duncan",
            "Louise Stranks",
            "Niall Urquhart",
            "Sarah Collin",
            "Shayne Attwood",
            "Simon Rayner",
            "Susan Sidey",
        }
        assert actual == expected

    def test_top_attender(self):
        totals = self.result.groupby("name")["attended"].sum()
        assert totals.idxmax() == "Graham Oak"
        assert totals.max() == 101

    def test_first_session_date(self):
        assert self.result["session_date"].min() == date(2024, 10, 14)

    def test_last_session_date(self):
        assert self.result["session_date"].max() == date(2025, 4, 12)

    def test_charity_bring_and_buy_sale_attendance(self):
        session = self.result[
            (self.result["session_name"] == "Charity Bring and Buy Sale")
            & (self.result["session_date"] == date(2025, 4, 12))
        ]
        assert session["attended"].sum() == 9


# ---------------------------------------------------------------------------
# test_full_pipeline
# ---------------------------------------------------------------------------


@data_dir_exists
class TestFullPipeline:
    """Run main() end-to-end with a few real files and verify outputs."""

    def test_output_files_created(self, two_files: Path, tmp_path: Path):
        output_dir = tmp_path / "output"
        main([str(two_files), "-o", str(output_dir), "--no-llm"])
        assert (output_dir / "spond.csv").exists()
        assert (output_dir / "session_attendance.csv").exists()

    def test_state_file_created(self, two_files: Path, tmp_path: Path):
        output_dir = tmp_path / "output"
        main([str(two_files), "-o", str(output_dir), "--no-llm"])
        assert (output_dir / ".spond_state.json").exists()

    def test_spond_csv_readable_with_expected_columns(
        self, two_files: Path, tmp_path: Path
    ):
        output_dir = tmp_path / "output"
        main([str(two_files), "-o", str(output_dir), "--no-llm"])
        df = pd.read_csv(output_dir / "spond.csv", sep="|")
        assert list(df.columns) == [
            "name",
            "session_name",
            "session_date",
            "session_day_of_week",
            "attended",
        ]
        assert len(df) > 0

    def test_session_attendance_csv_structure(self, two_files: Path, tmp_path: Path):
        output_dir = tmp_path / "output"
        main([str(two_files), "-o", str(output_dir), "--no-llm"])
        df = pd.read_csv(output_dir / "session_attendance.csv", sep="|")
        assert list(df.columns) == [
            "session_name",
            "session_date",
            "session_day_of_week",
            "attended",
        ]
        assert len(df) > 0
        # Attended count should be non-negative integers
        assert (df["attended"] >= 0).all()


# ---------------------------------------------------------------------------
# test_incremental_processing
# ---------------------------------------------------------------------------


@data_dir_exists
class TestIncrementalProcessing:
    """Verify that incremental processing only handles new files."""

    def test_no_new_files_message(self, two_files: Path, tmp_path: Path, capsys):
        output_dir = tmp_path / "output"

        # First run: processes 2 files.
        main([str(two_files), "-o", str(output_dir), "--no-llm"])
        captured = capsys.readouterr()
        assert "Processing 2 file(s)" in captured.out

        # Second run: no new files.
        main([str(two_files), "-o", str(output_dir), "--no-llm"])
        captured = capsys.readouterr()
        assert "No new files to process" in captured.out

    def test_third_file_triggers_incremental(
        self, two_files: Path, tmp_path: Path, capsys
    ):
        output_dir = tmp_path / "output"

        # First run: processes 2 files.
        main([str(two_files), "-o", str(output_dir), "--no-llm"])
        capsys.readouterr()

        # Copy a third file into the input directory.
        shutil.copy(
            DATA_DIR / "spond_attendance_may_25.xlsx",
            two_files / "spond_attendance_may_25.xlsx",
        )

        # Third run: should process only the new file.
        main([str(two_files), "-o", str(output_dir), "--no-llm"])
        captured = capsys.readouterr()
        assert "Processing 1 file(s)" in captured.out


# ---------------------------------------------------------------------------
# test_dedup_older_wins
# ---------------------------------------------------------------------------


@data_dir_exists
class TestDedupOlderWins:
    """Verify deduplication actually removes rows when files overlap."""

    def test_dedup_reduces_row_count(self, tmp_path: Path):
        # Pick two files likely to have overlapping sessions.
        files_to_use = [
            "spond_attendance_mar_24.xlsx",
            "spond_attendance_apr_24.xlsx",
        ]
        paths = []
        for name in files_to_use:
            dst = tmp_path / name
            shutil.copy(DATA_DIR / name, dst)
            paths.append(dst)

        # Sort oldest-first (discover_files does this, but be explicit).
        paths.sort(key=io.parse_file_date)

        # Process each file individually and sum their row counts.
        individual_total = 0
        for p in paths:
            raw = io.read_attendance_file(p)
            long = transform.transform_file(raw)
            # Filter to past dates (matching _deduplicate behaviour).
            long = long[long["session_date"] < date.today()]
            individual_total += len(long)

        # Process them together (with deduplication).
        combined = transform.process_files(paths)

        assert len(combined) < individual_total, (
            f"Expected dedup to reduce row count, but got "
            f"combined={len(combined)} vs individual_total={individual_total}"
        )
        # The combined result should still have a reasonable number of rows.
        assert len(combined) > 0
