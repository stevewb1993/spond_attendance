"""Wide-to-long transformation, deduplication, and output generation."""

from __future__ import annotations

import re
from datetime import date, datetime, time
from pathlib import Path

import pandas as pd

TIME_FORMAT = "%H:%M"

DETAIL_COLUMNS = (
    "name",
    "session_name",
    "session_date",
    "session_time",
    "session_day_of_week",
    "attended",
)

# Start time is part of a session's identity because two different sessions
# can share a date and, once raw Spond names are mapped to a canonical name,
# a name too (e.g. the morning and evening Friday social runs).
SESSION_IDENTITY_COLUMNS = ("session_name", "session_date", "session_time")

MEMBER_SESSION_KEY_COLUMNS = ("name", *SESSION_IDENTITY_COLUMNS)

# The summary deliberately leaves session_time out, so two sessions sharing a
# name and date (the morning and evening social runs) report as one figure.
SUMMARY_GROUP_COLUMNS = ("session_name", "session_date", "session_day_of_week")


def _parse_session_column(col) -> datetime | None:
    """Try to interpret a column header as a session datetime.

    Handles both raw datetime objects and strings with pandas
    duplicate-column suffixes like "2025-04-09 18:45:00.1".
    """
    if isinstance(col, datetime):
        return col
    if isinstance(col, pd.Timestamp):
        return col.to_pydatetime()
    if isinstance(col, str):
        cleaned = re.sub(r"\.\d+$", "", col)
        try:
            return datetime.fromisoformat(cleaned)
        except ValueError:
            return None
    return None


def _extract_session_info(df: pd.DataFrame) -> dict[str, tuple[str, date, time]]:
    """Build a mapping from column label to (session_name, session_date, session_time).

    Row 0 of the dataframe contains session names in session columns
    (and NaN in non-session columns). The column header itself is the
    session datetime.
    """
    session_info: dict[str, tuple[str, date, time]] = {}
    for col in df.columns:
        dt = _parse_session_column(col)
        if dt is not None:
            session_name = str(df[col].iloc[0]).strip().rstrip("*").strip()
            session_info[col] = (session_name, dt.date(), dt.time())
    return session_info


def transform_file(df: pd.DataFrame) -> pd.DataFrame:
    """Transform a single attendance file from wide to long format.

    Returns DataFrame with columns:
        name, session_name, session_date, session_time,
        session_day_of_week, attended
    """
    session_info = _extract_session_info(df)
    if not session_info:
        raise ValueError("No session columns found in file")

    session_columns = list(session_info.keys())

    # Row 0 contains session names (not attendance data) — skip it
    attendance = df.iloc[1:].copy()

    # Drop disclaimer rows (Name starts with "*Attendance") and NaN names
    attendance = attendance[
        attendance["Name"].notna()
        & ~attendance["Name"].astype(str).str.startswith("*Attendance")
    ]

    # Keep only Name + session columns
    attendance = attendance[["Name"] + session_columns]

    # Melt from wide to long
    melted = attendance.melt(
        id_vars=["Name"],
        value_vars=session_columns,
        var_name="_session_col",
        value_name="attended",
    )

    # Map session column back to session name, date, and start time
    melted["session_name"] = melted["_session_col"].map(
        {col: info[0] for col, info in session_info.items()}
    )
    melted["session_date"] = melted["_session_col"].map(
        {col: info[1] for col, info in session_info.items()}
    )
    melted["session_time"] = melted["_session_col"].map(
        {col: info[2].strftime(TIME_FORMAT) for col, info in session_info.items()}
    )
    melted["session_day_of_week"] = melted["_session_col"].map(
        {col: info[1].strftime("%A") for col, info in session_info.items()}
    )

    melted = melted.drop(columns=["_session_col"])
    melted = melted.rename(columns={"Name": "name"})

    # Convert attended: 1 -> 1, NaN/anything else -> 0
    melted["attended"] = (
        pd.to_numeric(melted["attended"], errors="coerce").fillna(0).astype(int)
    )

    return melted[list(DETAIL_COLUMNS)]


def load_files(files: list[Path]) -> pd.DataFrame:
    """Read and transform multiple attendance files into one long frame.

    Files must be sorted oldest-first; each row is tagged with its file's
    rank in that order. Session names are still raw, and nothing is
    deduplicated yet: callers map the names to canonical ones first, then
    call deduplicate. Mapping afterwards would leave two rows for a
    session whose raw names differ only in the source export.
    """
    from .io import read_attendance_file

    all_frames = []
    for file_rank, path in enumerate(files):
        long_df = transform_file(read_attendance_file(path))
        long_df["_source_rank"] = file_rank
        all_frames.append(long_df)

    return pd.concat(all_frames, ignore_index=True)


def merge_with_existing(existing: pd.DataFrame, new: pd.DataFrame) -> pd.DataFrame:
    """Merge new data into existing output.

    Existing rows are kept whether or not the new export still reports
    them, because members who leave the club disappear from newer Spond
    exports. See deduplicate for how conflicting values are resolved.
    """
    existing["_source_rank"] = 0
    new["_source_rank"] = 1
    combined = pd.concat([existing, new], ignore_index=True)
    return deduplicate(combined)


def deduplicate(df: pd.DataFrame) -> pd.DataFrame:
    """Collapse each member/session key to one row, keeping the highest
    attended value and, where those tie, the oldest source.

    Taking the highest value picks up registers completed after an export
    was taken, and copes with Spond holding one session twice with a copy
    left empty. It never drops a member: a key that only an older export
    knows about has nothing to compete with, so members who have since
    left the club keep their history.
    """
    required = ("_source_rank", "attended", *MEMBER_SESSION_KEY_COLUMNS)
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise KeyError(f"Cannot deduplicate without column(s): {', '.join(missing)}")

    today = date.today()

    df = df.sort_values(["attended", "_source_rank"], ascending=[False, True])
    df = df.drop_duplicates(subset=list(MEMBER_SESSION_KEY_COLUMNS), keep="first")
    df = df.drop(columns=["_source_rank"])

    # Filter out future sessions
    df = df[df["session_date"] < today]

    return df.sort_values(
        ["session_date", "session_time", "session_name", "name"]
    ).reset_index(drop=True)


def generate_outputs(df: pd.DataFrame, output_dir: Path) -> tuple[Path, Path]:
    """Write the two output CSVs."""
    output_dir.mkdir(parents=True, exist_ok=True)

    # Detailed attendance
    detail_path = output_dir / "spond.csv"
    df.to_csv(detail_path, sep="|", index=False)

    # Session summary
    session_attendance = (
        df.groupby(list(SUMMARY_GROUP_COLUMNS))["attended"]
        .sum()
        .reset_index()
        .sort_values(["session_date", "session_name"])
    )
    summary_path = output_dir / "session_attendance.csv"
    session_attendance.to_csv(summary_path, sep="|", index=False)

    return detail_path, summary_path
