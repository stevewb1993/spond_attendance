"""CLI entry point for spond-attendance processing."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

from .io import discover_files, find_new_files, load_state, save_state
from .mapping import (
    SKIP_SENTINEL,
    apply_name_mappings,
    find_unmapped_names,
    load_canonical_names,
    load_name_mappings,
    load_session_types,
    prompt_user_approval,
    save_name_mappings,
    save_session_types,
    suggest_categories,
    suggest_mappings,
)
from .transform import generate_outputs, merge_with_existing, process_files


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="spond-attendance",
        description="Process Spond attendance exports into tidy CSV files.",
    )
    parser.add_argument(
        "input_dir",
        type=Path,
        help="Directory containing spond_attendance_*.xlsx files",
    )
    parser.add_argument(
        "-o", "--output-dir",
        type=Path,
        default=None,
        help="Output directory for CSV files (default: output_data/ in current directory)",
    )
    parser.add_argument(
        "--full-refresh",
        action="store_true",
        help="Reprocess all files, ignoring state",
    )
    parser.add_argument(
        "--no-llm",
        action="store_true",
        help="Skip Claude API suggestions for unmapped session names",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)

    input_dir = args.input_dir.resolve()
    output_dir = (args.output_dir or Path("output_data")).resolve()

    if not input_dir.is_dir():
        print(f"Error: {input_dir} is not a directory", file=sys.stderr)
        sys.exit(1)

    all_files = discover_files(input_dir)
    if not all_files:
        print(f"Error: No spond_attendance_*.xlsx files found in {input_dir}", file=sys.stderr)
        sys.exit(1)

    if args.full_refresh:
        files_to_process = all_files
    else:
        processed = load_state(output_dir)
        files_to_process = find_new_files(all_files, processed)

    if not files_to_process:
        print("No new files to process.")
        return

    print(f"Processing {len(files_to_process)} file(s):")
    for f in files_to_process:
        print(f"  {f.name}")

    new_data = process_files(files_to_process)

    # Merge with existing output if doing incremental processing
    existing_csv = output_dir / "spond.csv"
    if not args.full_refresh and existing_csv.exists():
        existing = pd.read_csv(existing_csv, sep="|", parse_dates=["session_date"])
        existing["session_date"] = existing["session_date"].dt.date
        result = merge_with_existing(existing, new_data)
    else:
        result = new_data

    # Session name mapping: normalize raw names to canonical parsed names
    mappings_path = output_dir / "session_name_mappings.csv"
    types_path = output_dir / "session_types.csv"

    mappings = load_name_mappings(mappings_path)
    canonical_names = load_canonical_names(types_path)

    all_session_names = set(result["session_name"].unique())
    unmapped = find_unmapped_names(all_session_names, mappings, canonical_names)

    if unmapped:
        print(f"\n{len(unmapped)} unmapped session name(s) found:")
        for name in sorted(unmapped):
            print(f"  - {name}")

        if not args.no_llm:
            print("\nAsking Claude for mapping suggestions...")
            suggestions = suggest_mappings(unmapped, canonical_names)
            print()
            approved, skipped = prompt_user_approval(suggestions)
            if approved or skipped:
                mappings.update(approved)
                for name in skipped:
                    mappings[name] = SKIP_SENTINEL
                save_name_mappings(mappings_path, mappings)
                saved = len(approved) + len(skipped)
                print(f"\n{saved} mapping(s) saved to {mappings_path}" + (f" ({len(skipped)} skipped)" if skipped else ""))
        else:
            print("\n(Skipping LLM suggestions — use without --no-llm to get suggestions)")

    result = apply_name_mappings(result, mappings)

    # Categorize session names missing from session_types.csv
    # Exclude names that were explicitly skipped in the mapping step
    skipped_names = {k for k, v in mappings.items() if v == SKIP_SENTINEL}
    uncategorized = set(result["session_name"].unique()) - canonical_names - skipped_names
    if uncategorized:
        print(f"\n{len(uncategorized)} session name(s) missing from {types_path.name}:")
        for name in sorted(uncategorized):
            print(f"  - {name}")

        if not args.no_llm:
            print("\nAsking Claude for category suggestions...")
            existing_types = load_session_types(types_path)
            cat_suggestions = suggest_categories(uncategorized, existing_types)
            print()
            approved_cats, _skipped_cats = prompt_user_approval(cat_suggestions)
            if approved_cats:
                existing_types.update(approved_cats)
                save_session_types(types_path, existing_types)
                print(f"\n{len(approved_cats)} category assignment(s) saved to {types_path}")
        else:
            print("(Add these to session_types.csv to assign categories)")

    detail_path, summary_path = generate_outputs(result, output_dir)

    # Update state with all files that are now accounted for
    all_processed = {f.name for f in all_files} if args.full_refresh else load_state(output_dir) | {f.name for f in files_to_process}
    save_state(output_dir, all_processed)

    sessions = result.groupby(["session_name", "session_date"]).ngroups
    print(f"\nOutput written:")
    print(f"  {detail_path}  ({len(result)} rows)")
    print(f"  {summary_path}  ({sessions} sessions)")
