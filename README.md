# spond-attendance

Processes Spond attendance Excel exports (.xlsx) into tidy CSV files for analysis. Built for Bath Amphibians Triathlon Club.

## What it does

Spond exports attendance data in wide format, with sessions as columns and members as rows. This tool:

1. Reads `spond_attendance_*.xlsx` files from an input directory
2. Transforms wide-format data into long/tidy format (name, session_name, session_date, session_time, day_of_week, attended)
3. Normalizes raw session names to canonical ones, then deduplicates across files -- the oldest source wins, since departed members disappear from newer exports
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
| `--full-refresh` | Reprocess all files, ignoring saved state. Applied automatically when the existing `spond.csv` predates session-time tracking |
| `--no-llm` | Skip Claude API suggestions for unmapped session names |

Example:

```
spond-attendance ./exports -o ./output_data
spond-attendance ./exports --no-llm --full-refresh
```

## Downloading exports from Spond

`spond-fetch` downloads the attendance export straight from the Spond API — the same file as the web client's **Export attendance history** button — so there is no need to pick events by hand or record requests in the browser's network tab.

```
spond-fetch [output_dir] [--months N | --since YYYY-MM-DD] [--until YYYY-MM-DD] [--force] [--dry-run]
```

| Argument | Description |
|---|---|
| `output_dir` | Where to save the export (defaults to `data/`) |
| `--months` | Whole months to include before this one (default 3, so a run on 19 October covers 1 July to 19 October) |
| `--since` | First event date, instead of `--months` |
| `--until` | Last event date (defaults to today). The file is named after its month: `spond_attendance_YYYY-MM.xlsx` |
| `--force` | Replace this month's export if it already exists. Follow up with `spond-attendance --full-refresh`, because the pipeline skips filenames it has already processed |
| `--dry-run` | List the events that would be exported without downloading |
| `--group-id` | Spond group (defaults to Bath Amphibians, or `SPOND_GROUP_ID`) |

Sign-in details come from `SPOND_USERNAME` and `SPOND_PASSWORD`, read from the environment or from a `.env` file (gitignored) in the repo root, the same as spond-cancellation:

```
SPOND_USERNAME=you@example.com
SPOND_PASSWORD=...
```

Without them, `spond-fetch` prompts for your email and password, plus a texted code if your account uses two-factor sign-in. The sign-in tokens are cached in `~/.config/spond-attendance/tokens.json`, and later runs refresh them without asking again (the refresh token lasts about 90 days). To use a token copied from the browser instead, set `SPOND_TOKEN`.

A typical monthly update:

```
spond-fetch
spond-attendance ./data -o ./output_data
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
