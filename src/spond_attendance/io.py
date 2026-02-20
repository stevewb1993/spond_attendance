"""File discovery, date parsing, Excel reading, and state tracking."""

from __future__ import annotations

import json
import re
import warnings
from datetime import date
from pathlib import Path

import pandas as pd

MONTH_MAP = {
    "jan": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "may": 5,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "sep": 9,
    "sept": 9,
    "oct": 10,
    "nov": 11,
    "dec": 12,
}

FILENAME_PATTERN = re.compile(
    r"spond_attendance_([a-z]+)_(\d{2})\.xlsx$", re.IGNORECASE
)

STATE_FILENAME = ".spond_state.json"


def parse_file_date(path: Path) -> date:
    """Extract the month/year from a Spond attendance filename.

    Returns a date (first of month) for ordering purposes.
    """
    match = FILENAME_PATTERN.search(path.name)
    if not match:
        raise ValueError(f"Filename does not match expected pattern: {path.name}")
    month_str, year_str = match.groups()
    month = MONTH_MAP.get(month_str.lower())
    if month is None:
        raise ValueError(f"Unrecognized month abbreviation: {month_str!r}")
    year = 2000 + int(year_str)
    return date(year, month, 1)


def discover_files(directory: Path) -> list[Path]:
    """Find all attendance Excel files in directory, sorted oldest-first.

    Raises ValueError if any .xlsx file doesn't match the expected
    naming pattern spond_attendance_{month}_{yy}.xlsx.
    """
    unexpected = []
    files = []
    for f in directory.glob("*.xlsx"):
        if f.name.startswith("~$"):
            continue
        try:
            parse_file_date(f)
            files.append(f)
        except ValueError:
            unexpected.append(f.name)
    if unexpected:
        raise ValueError(
            f"Unexpected xlsx file(s) in directory: {', '.join(sorted(unexpected))}. "
            f"Expected format: spond_attendance_{{month}}_{{yy}}.xlsx"
        )
    files.sort(key=parse_file_date)
    return files


def read_attendance_file(path: Path) -> pd.DataFrame:
    """Read a single Spond attendance Excel export."""
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", message="Workbook contains no default style")
        return pd.read_excel(path, engine="openpyxl")


def load_state(output_dir: Path) -> set[str]:
    """Load the set of previously processed filenames from state file."""
    state_path = output_dir / STATE_FILENAME
    if not state_path.exists():
        return set()
    data = json.loads(state_path.read_text())
    return set(data.get("processed_files", []))


def save_state(output_dir: Path, processed_files: set[str]) -> None:
    """Save the set of processed filenames to state file."""
    state_path = output_dir / STATE_FILENAME
    data = {"processed_files": sorted(processed_files)}
    state_path.write_text(json.dumps(data, indent=2) + "\n")


def find_new_files(all_files: list[Path], processed: set[str]) -> list[Path]:
    """Return only files not yet in the processed set."""
    return [f for f in all_files if f.name not in processed]
