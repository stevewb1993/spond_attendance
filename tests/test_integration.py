"""Integration tests using real Spond xlsx files."""

from __future__ import annotations

import shutil
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from spond_attendance import io, transform
from spond_attendance.cli import main
from spond_attendance.transform import MEMBER_SESSION_KEY_COLUMNS

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
    src = DATA_DIR / "spond_attendance_2025-04.xlsx"
    dst = tmp_path / src.name
    shutil.copy(src, dst)
    return dst


@pytest.fixture()
def two_files(tmp_path: Path) -> Path:
    """Copy two chronologically adjacent xlsx files to a temp directory."""
    names = [
        "spond_attendance_2024-03.xlsx",
        "spond_attendance_2024-04.xlsx",
    ]
    for name in names:
        shutil.copy(DATA_DIR / name, tmp_path / name)
    return tmp_path


@pytest.fixture()
def three_files(tmp_path: Path) -> Path:
    """Copy three xlsx files to a temp directory."""
    names = [
        "spond_attendance_2024-03.xlsx",
        "spond_attendance_2024-04.xlsx",
        "spond_attendance_2025-05.xlsx",
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
            "session_time",
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
# test_attendance_figures (spond_attendance_2025-04.xlsx)
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
            "session_time",
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
            DATA_DIR / "spond_attendance_2025-05.xlsx",
            two_files / "spond_attendance_2025-05.xlsx",
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
            "spond_attendance_2024-03.xlsx",
            "spond_attendance_2024-04.xlsx",
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
            # Filter to past dates (matching deduplicate behaviour).
            long = long[long["session_date"] < date.today()]
            individual_total += len(long)

        # Process them together (with deduplication).
        combined = transform.deduplicate(transform.load_files(paths))

        assert len(combined) < individual_total, (
            f"Expected dedup to reduce row count, but got "
            f"combined={len(combined)} vs individual_total={individual_total}"
        )
        # The combined result should still have a reasonable number of rows.
        assert len(combined) > 0


# ---------------------------------------------------------------------------
# test_incremental_name_mapping
# ---------------------------------------------------------------------------


@data_dir_exists
class TestIncrementalNameMapping:
    """Incremental runs must not double-count renamed sessions.

    An earlier version deduplicated before mapping raw Spond names to
    canonical ones, so a session already written under its canonical name
    survived the merge again under its raw name and its attendance doubled.
    """

    AQUATHLON = "STV Swim - Aquathlon"
    AQUATHLON_DATE = "2026-07-25"

    @pytest.fixture()
    def output_dir(self, tmp_path: Path) -> Path:
        output_dir = tmp_path / "output"
        output_dir.mkdir()
        (output_dir / "session_name_mappings.csv").write_text(
            "raw_session_name,parsed_session_name\n"
            f"STV Swim - club aquathon,{self.AQUATHLON}\n"
        )
        (output_dir / "session_types.csv").write_text(
            f"session_name,category\n{self.AQUATHLON},Swim\n"
        )
        return output_dir

    @staticmethod
    def _input_dir(tmp_path: Path, *names: str) -> Path:
        input_dir = tmp_path / "input"
        input_dir.mkdir(exist_ok=True)
        for name in names:
            shutil.copy(DATA_DIR / name, input_dir / name)
        return input_dir

    def _attendance(self, output_dir: Path) -> int:
        summary = pd.read_csv(output_dir / "session_attendance.csv", sep="|")
        row = summary[
            (summary["session_name"] == self.AQUATHLON)
            & (summary["session_date"] == self.AQUATHLON_DATE)
        ]
        assert len(row) == 1
        return int(row.iloc[0]["attended"])

    def test_attendance_unchanged_by_a_later_export(
        self, tmp_path: Path, output_dir: Path
    ):
        input_dir = self._input_dir(tmp_path, "spond_attendance_2026-08.xlsx")
        main([str(input_dir), "-o", str(output_dir), "--no-llm"])
        first_run = self._attendance(output_dir)
        assert first_run == 20

        # A later export reports the same session under its raw name again.
        self._input_dir(tmp_path, "spond_attendance_2026-10.xlsx")
        main([str(input_dir), "-o", str(output_dir), "--no-llm"])

        assert self._attendance(output_dir) == first_run

    def test_no_duplicate_session_keys_after_merge(
        self, tmp_path: Path, output_dir: Path
    ):
        input_dir = self._input_dir(tmp_path, "spond_attendance_2026-08.xlsx")
        main([str(input_dir), "-o", str(output_dir), "--no-llm"])
        self._input_dir(tmp_path, "spond_attendance_2026-10.xlsx")
        main([str(input_dir), "-o", str(output_dir), "--no-llm"])

        detail = pd.read_csv(output_dir / "spond.csv", sep="|")
        duplicates = detail[detail.duplicated(subset=list(MEMBER_SESSION_KEY_COLUMNS))]
        assert duplicates.empty, (
            f"{len(duplicates)} duplicated member/session rows after merge"
        )


@data_dir_exists
class TestDuplicatedSpondSession:
    """A session held twice in Spond, with one copy empty, keeps its register.

    On 2025-04-02 the club run appears as two 18:45 columns whose raw names
    differ only in case; one records 10 attendances and the other none.
    """

    CLUB_RUN = "Club Run Session - Green Members"

    def test_empty_copy_does_not_erase_or_double_attendance(self, tmp_path: Path):
        input_dir = tmp_path / "input"
        input_dir.mkdir()
        shutil.copy(
            DATA_DIR / "spond_attendance_2025-04.xlsx",
            input_dir / "spond_attendance_2025-04.xlsx",
        )
        output_dir = tmp_path / "output"
        output_dir.mkdir()
        (output_dir / "session_name_mappings.csv").write_text(
            "raw_session_name,parsed_session_name\n"
            f"Club Run Session - update self led session ( no coach),{self.CLUB_RUN}\n"
            f"Club Run Session - Update self led session ( no coach),{self.CLUB_RUN}\n"
        )

        main([str(input_dir), "-o", str(output_dir), "--no-llm"])

        summary = pd.read_csv(output_dir / "session_attendance.csv", sep="|")
        row = summary[
            (summary["session_name"] == self.CLUB_RUN)
            & (summary["session_date"] == "2025-04-02")
        ]
        assert len(row) == 1
        assert int(row.iloc[0]["attended"]) == 10


@data_dir_exists
class TestDepartedMembersSurvive:
    """Members who leave the club must keep their history.

    They disappear from newer Spond exports, so an incremental run has to
    carry their rows forward from the output it already wrote.
    """

    @staticmethod
    def _run(input_dir: Path, output_dir: Path, *names: str) -> pd.DataFrame:
        for name in names:
            shutil.copy(DATA_DIR / name, input_dir / name)
        main([str(input_dir), "-o", str(output_dir), "--no-llm"])
        return pd.read_csv(output_dir / "spond.csv", sep="|")

    def test_history_survives_a_later_export(self, tmp_path: Path):
        input_dir = tmp_path / "input"
        input_dir.mkdir()
        output_dir = tmp_path / "output"

        before = self._run(input_dir, output_dir, "spond_attendance_2024-03.xlsx")
        after = self._run(input_dir, output_dir, "spond_attendance_2026-10.xlsx")

        # The newer export has dropped members the older one knew about.
        departed = set(before["name"]) - set(
            transform.transform_file(
                io.read_attendance_file(input_dir / "spond_attendance_2026-10.xlsx")
            )["name"]
        )
        assert departed, "expected the newer export to have dropped some members"
        assert departed <= set(after["name"]), "departed members lost from the output"

        # No member loses attendance, and the departed keep every session.
        totals_before = before.groupby("name")["attended"].sum()
        totals_after = after.groupby("name")["attended"].sum()
        regressed = totals_after.lt(totals_before.reindex(totals_after.index)).sum()
        assert regressed == 0, f"{regressed} member(s) lost attendance"

        rows_before = before[before["name"].isin(departed)]
        rows_after = after[after["name"].isin(departed)]
        assert len(rows_after) == len(rows_before)
        assert rows_after["attended"].sum() == rows_before["attended"].sum()

    def test_merged_figures_match_the_newer_export(self, tmp_path: Path):
        """Two real sessions pin both ways an export can revise a register.

        The March 2024 export reports the 13 March club run as 3 and the
        12 March indoor bike as 14. The April export completes the club
        run register to 8, and leaves the indoor bike at 14 while marking
        four of its attendees absent and four others present. Both merged
        figures must follow the April export: 8 and 14. Taking the highest
        value per member instead gives 14 and 18.
        """
        input_dir = tmp_path / "input"
        input_dir.mkdir()
        output_dir = tmp_path / "output"

        self._run(input_dir, output_dir, "spond_attendance_2024-03.xlsx")
        self._run(input_dir, output_dir, "spond_attendance_2024-04.xlsx")

        summary = pd.read_csv(output_dir / "session_attendance.csv", sep="|")

        def figure(session_name: str, session_date: str) -> int:
            row = summary[
                (summary["session_name"] == session_name)
                & (summary["session_date"] == session_date)
            ]
            assert len(row) == 1
            return int(row.iloc[0]["attended"])

        assert figure("Club Run Session - Green Members", "2024-03-13") == 8
        assert figure("Indoor Bike", "2024-03-12") == 14
