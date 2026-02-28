Draft a concise attendance update email for the Bath Amphibians Triathlon Club committee.

## Sessions to include

Only analyse these sessions. Ignore everything else.

| Label for email          | session_name(s) in data                                              | Notes |
|--------------------------|----------------------------------------------------------------------|-------|
| STV Swim                 | `STV Swim`                                                           | Split by day of week — report each day separately |
| STV Swim - Technique     | `STV swim - technique`                                               | Split by day of week — report each day separately |
| S&C                      | `S&C`                                                                | Split by day of week — report each day separately |
| Indoor Bike              | `Indoor Bike`                                                        | Split by day of week — report each day separately |
| Club Run                 | `Club Run Session - Green Members` + `Club Run Session - Associates PAYG` | Combine both into a single "Club Run" total per date, then split by day of week |

**Important:** Sessions often run on multiple days of the week with very different attendance patterns. Always discover which days each session runs from the data itself (do not hardcode days). Treat each (session, day_of_week) combination as a separate series for analysis and reporting (e.g. "Monday Swim", "Wednesday Swim", "Saturday Swim").

## Steps

1. **Read previous emails** from the `emails/` directory to match the tone, format, and level of detail. Build on what was said previously where relevant.

2. **Load the data** by reading `output_data/session_attendance.csv` (pipe-separated). Use Python/pandas via Bash to run the analysis.

3. **Analyse each session/day combination** (grouped under Swim, Bike, Run, S&C):
   - Compare average session attendance for the **most recent complete month** vs the **previous month** (month-over-month change)
   - Compare vs the **same month last year** (year-over-year change)
   - Where sessions are split by day, report each day's trend separately

4. **Draft the email**:
   - Short intro line (1 sentence)
   - One section per category (Swim, Bike, Run, S&C) — covering each session/day within it
   - Keep it concise and conversational — this is an informal committee update, not a formal report
   - Include the actual numbers where they tell the story (e.g. "Thursday swim technique averaging 12, up from 8 last month")
   - End with a brief summary/outlook if there's anything worth calling out

5. **Save the draft** to `emails/` with the filename pattern `YYYY-MM-draft.md` (using the month being reported on).

## Important
- Be data-driven — every claim should be backed by the numbers
- Don't pad it out — committee members are busy, shorter is better
- If a session/day is stable and unremarkable, say so briefly and move on
- Flag anything genuinely interesting or concerning
