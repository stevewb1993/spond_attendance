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

# A session is identified by its name, date, and start time. The start time
# matters because two different sessions can share a date and, once raw Spond
# names are mapped to a canonical name, a name too (e.g. the morning and
# evening Friday social runs).
SESSION_KEY_COLUMNS = ("name", "session_name", "session_date", "session_time")


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
    melted["session_name"] = melted["_session_col"].map(lambda c: session_info[c][0])
    melted["session_date"] = melted["_session_col"].map(lambda c: session_info[c][1])
    melted["session_time"] = melted["_session_col"].map(
        lambda c: session_info[c][2].strftime(TIME_FORMAT)
    )
    melted["session_day_of_week"] = melted["session_date"].apply(
        lambda d: d.strftime("%A")
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
    """Merge new data with existing output, deduplicating so existing wins.

    Existing (older) data takes priority because members who leave the
    club disappear from newer Spond exports.
    """
    existing["_source_rank"] = 0
    new["_source_rank"] = 1
    combined = pd.concat([existing, new], ignore_index=True)
    return deduplicate(combined)


def deduplicate(df: pd.DataFrame) -> pd.DataFrame:
    """Deduplicate rows: for each session key, keep the row from the
    lowest _source_rank (oldest source wins).

    Within one source, a recorded attendance wins, because a key can
    collide there only when Spond holds the same session twice (often
    with one copy left empty).
    """
    missing = [c for c in SESSION_KEY_COLUMNS if c not in df.columns]
    if missing:
        raise KeyError(
            f"Cannot deduplicate without session key column(s): {', '.join(missing)}"
        )

    today = date.today()

    df = df.sort_values(["_source_rank", "attended"], ascending=[True, False])
    df = df.drop_duplicates(subset=list(SESSION_KEY_COLUMNS), keep="first")
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
        df.groupby(["session_name", "session_date", "session_day_of_week"])["attended"]
        .sum()
        .reset_index()
        .sort_values(["session_date", "session_name"])
    )
    summary_path = output_dir / "session_attendance.csv"
    session_attendance.to_csv(summary_path, sep="|", index=False)

    return detail_path, summary_path
