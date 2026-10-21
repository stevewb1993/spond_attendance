"""Download this month's Spond export and run the processing pipeline."""

from __future__ import annotations

import argparse
import os
import sys
from datetime import date
from pathlib import Path

from dotenv import find_dotenv, load_dotenv

from . import cli
from .fetch import (
    DEFAULT_GROUP_ID,
    DEFAULT_MONTHS,
    SpondError,
    download_export,
    export_filename,
    start_of_month_before,
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="spond-update",
        description=(
            "Download this month's attendance export from Spond, then process "
            "every export into the output CSVs."
        ),
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=Path("data"),
        help="Directory of spond_attendance_*.xlsx exports (default: data/)",
    )
    parser.add_argument(
        "-o",
        "--output-dir",
        type=Path,
        default=Path("output_data"),
        help="Output directory for CSV files (default: output_data/)",
    )
    parser.add_argument(
        "--months",
        type=int,
        default=DEFAULT_MONTHS,
        help=f"Include this many whole months before this one "
        f"(default: {DEFAULT_MONTHS})",
    )
    parser.add_argument(
        "--no-llm",
        action="store_true",
        help="Skip Claude suggestions for unmapped session names",
    )
    parser.add_argument(
        "-y",
        "--yes",
        action="store_true",
        help="Accept Claude's suggestions without asking, for unattended runs",
    )
    parser.add_argument(
        "--group-id",
        default=os.environ.get("SPOND_GROUP_ID", DEFAULT_GROUP_ID),
        help="Spond group ID (default: Bath Amphibians)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    load_dotenv(find_dotenv(usecwd=True))
    args = parse_args(argv)
    until = date.today()
    since = start_of_month_before(until, args.months)

    data_dir = args.data_dir.resolve()
    export_path = data_dir / export_filename(until)
    replacing = export_path.exists()
    if replacing:
        print(f"Replacing {export_path.name}, this month's earlier export.")

    try:
        downloaded = download_export(export_path, args.group_id, since, until)
    except SpondError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    if not downloaded:
        return

    pipeline_args = [str(data_dir), "-o", str(args.output_dir)]
    # The pipeline remembers exports by filename, so a replaced export is only
    # read again on a full refresh.
    if replacing:
        pipeline_args.append("--full-refresh")
    if args.no_llm:
        pipeline_args.append("--no-llm")
    if args.yes:
        pipeline_args.append("--yes")
    print("\nProcessing exports...")
    cli.main(pipeline_args)
