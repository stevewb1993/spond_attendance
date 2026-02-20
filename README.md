# spond-attendance

Processes Spond attendance Excel exports (.xlsx) into tidy CSV files for analysis. Built for Bath Amphibians Triathlon Club.

## What it does

Spond exports attendance data in wide format, with sessions as columns and members as rows. This tool:

1. Reads `spond_attendance_*.xlsx` files from an input directory
2. Transforms wide-format data into long/tidy format (name, session_name, session_date, day_of_week, attended)
3. Deduplicates across files -- the oldest source wins, since departed members disappear from newer exports
4. Supports incremental processing by tracking which files have already been handled
5. Optionally uses Claude CLI to suggest session name mappings and categories for unmapped sessions
6. Outputs two CSV files:
   - `spond.csv` -- detailed per-member, per-session attendance
   - `session_attendance.csv` -- summary counts per session

A Streamlit dashboard provides monthly trends, year-over-year comparisons, and per-session detail.

## Requirements

- Python 3.12
- [uv](https://docs.astral.sh/uv/) for dependency management
- Optional: [Claude CLI](https://docs.anthropic.com/en/docs/claude-code) (Claude Code) for AI-assisted session name mapping and categorization

## Installation

```
uv sync
```

For development:

```
uv sync --group dev
```

## CLI usage

```
spond-attendance <input_dir> [-o output_dir] [--full-refresh] [--no-llm]
```

| Argument | Description |
|---|---|
| `input_dir` | Directory containing `spond_attendance_*.xlsx` files |
| `-o output_dir` | Output directory (defaults to `output_data/` in current directory) |
| `--full-refresh` | Reprocess all files, ignoring saved state |
| `--no-llm` | Skip Claude API suggestions for unmapped session names |

Example:

```
spond-attendance ./exports -o ./output_data
spond-attendance ./exports --no-llm --full-refresh
```

## Dashboard

```
streamlit run dashboard/app.py
```

Reads CSV output from the `output_data/` directory.

## Running tests

```
uv run pytest
```

## Key dependencies

- pandas, openpyxl -- data processing and Excel reading
- streamlit, plotly -- interactive dashboard
- hatchling -- build system
