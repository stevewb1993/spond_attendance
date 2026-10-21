# Spond Attendance — Bath Amphibians Triathlon Club

This project processes Spond attendance exports into tidy CSVs for analysis and visualization.

## Output data (in `output_data/`)

### `session_attendance.csv` (pipe-separated)
Aggregated attendance per session. Columns: `session_name|session_date|session_day_of_week|attended` (attended = headcount).

### `spond.csv` (pipe-separated)
Per-member attendance. Columns: `name|session_name|session_date|session_time|session_day_of_week|attended` (attended = 0 or 1). `session_time` is the session start time (`HH:MM`); it is part of a session's identity, so two sessions on one date are kept apart even when they share a name.

### `session_types.csv` (comma-separated)
Maps session names to categories: Swim, Bike, Run, S&C, Other.

### `session_name_mappings.csv` (comma-separated)
Maps raw Spond session names to canonical names. `__SKIP__` means ignore.

## Session categories and their sessions

- **Swim**: STV Swim (Mon/Wed/Sat), STV swim - technique (Thu), Vobster open water session, STV Swim - Aquathlon
- **Bike**: Indoor Bike (Tue/Thu), Indoor Bike ONLINE, Odd Down bike session/skills, Gears for Beers, Activator ride
- **Run**: Club Run Session - Green Members (Wed), Club Run Session - Associates PAYG (Wed), Social Run 7@7 (Fri)
- **S&C**: S&C (Mon/Fri)
- **Other**: Social events, AGM, one-off events

## Data range

Monthly exports in `data/` cover February 2024 to October 2026 (and growing). Each export is cumulative, so sessions back to July 2023 appear in the output.

## Previous committee emails

See `emails/` for previously sent attendance update emails. Use these for tone and format context when drafting new ones.

## Commands

- `uv run pytest` — run tests
- `uv run ruff check` — lint
- `spond-email` — email last month's YoY Summary table (the dashboard's) to the committee via Brevo; `--dry-run` to preview. GitHub Actions runs `spond-update` then this on the 2nd of each month (`.github/workflows/monthly-email.yml`)
- `spond-update` — monthly update: download this month's export, then run the pipeline (full refresh when it replaces an export)
- `spond-fetch` — download this month's export (this month plus the 3 before it) from the Spond API into `data/`
- `spond-attendance ./data -o ./output_data` — run the pipeline
- `streamlit run dashboard/app.py` — launch dashboard
