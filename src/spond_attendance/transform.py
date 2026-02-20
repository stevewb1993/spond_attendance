"""Wide-to-long transformation, deduplication, and output generation."""

from __future__ import annotations

import re
from datetime import date, datetime
from pathlib import Path

import pandas as pd


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


def _extract_session_info(df: pd.DataFrame) -> dict[str, tuple[str, date]]:
    """Build a mapping from column label to (session_name, session_date).

    Row 0 of the dataframe contains session names in session columns
    (and NaN in non-session columns). The column header itself is the
    session datetime.
    """
    session_info: dict[str, tuple[str, date]] = {}
    for col in df.columns:
        dt = _parse_session_column(col)
        if dt is not None:
            session_name = str(df[col].iloc[0]).strip().rstrip("*").strip()
            session_date = dt.date()
            session_info[col] = (session_name, session_date)
    return session_info


def transform_file(df: pd.DataFrame) -> pd.DataFrame:
    """Transform a single attendance file from wide to long format.

    Returns DataFrame with columns:
        name, session_name, session_date, session_day_of_week, attended
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

    # Map session column back to session name and date
    melted["session_name"] = melted["_session_col"].map(lambda c: session_info[c][0])
    melted["session_date"] = melted["_session_col"].map(lambda c: session_info[c][1])
    melted["session_day_of_week"] = melted["session_date"].apply(
        lambda d: d.strftime("%A")
    )

    melted = melted.drop(columns=["_session_col"])
    melted = melted.rename(columns={"Name": "name"})

    # Convert attended: 1 -> 1, NaN/anything else -> 0
    melted["attended"] = (
        pd.to_numeric(melted["attended"], errors="coerce").fillna(0).astype(int)
    )

    return melted[
        ["name", "session_name", "session_date", "session_day_of_week", "attended"]
    ]


def process_files(files: list[Path]) -> pd.DataFrame:
    """Process multiple attendance files with deduplication.

    Files must be sorted oldest-first. When a session appears in
    multiple files, the oldest version wins (members who leave the
    club disappear from newer exports).
    """
    from .io import read_attendance_file

    all_frames = []
    for file_rank, path in enumerate(files):
        raw_df = read_attendance_file(path)
        long_df = transform_file(raw_df)
        long_df["_source_rank"] = file_rank
        all_frames.append(long_df)

    combined = pd.concat(all_frames, ignore_index=True)
    return _deduplicate(combined)


def merge_with_existing(existing: pd.DataFrame, new: pd.DataFrame) -> pd.DataFrame:
    """Merge new data with existing output, deduplicating so existing wins.

    Existing (older) data takes priority because members who leave the
    club disappear from newer Spond exports.
    """
    existing["_source_rank"] = 0
    new["_source_rank"] = 1
    combined = pd.concat([existing, new], ignore_index=True)
    return _deduplicate(combined)


def _deduplicate(df: pd.DataFrame) -> pd.DataFrame:
    """Deduplicate rows: for each (name, session_name, session_date),
    keep the row from the lowest _source_rank (oldest source wins)."""
    today = date.today()

    df = df.sort_values("_source_rank")
    df = df.drop_duplicates(
        subset=["name", "session_name", "session_date"],
        keep="first",
    )
    df = df.drop(columns=["_source_rank"])

    # Filter out future sessions
    df = df[df["session_date"] < today]

    return df.sort_values(["session_date", "session_name", "name"]).reset_index(
        drop=True
    )


def generate_outputs(df: pd.DataFrame, output_dir: Path) -> tuple[Path, Path]:
    """Write the two output CSVs."""
    output_dir.mkdir(parents=True, exist_ok=True)

    # Detailed attendance
    detail_path = output_dir / "spond.csv"
    df.to_csv(detail_path, sep="|", index=False)

    # Session summary
    session_attendance = (
        df.groupby(["session_name", "session_date", "session_day_of_week"])["attended"]
        .sum()
        .reset_index()
        .sort_values(["session_date", "session_name"])
    )
    summary_path = output_dir / "session_attendance.csv"
    session_attendance.to_csv(summary_path, sep="|", index=False)

    return detail_path, summary_path
