"""Year-over-year attendance summary: the table the committee email carries."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

# Sessions shown by default, per category, in the order the table lists them
DEFAULT_SESSIONS: dict[str, list[str]] = {
    "Swim": ["STV Swim", "STV swim - technique"],
    "Bike": ["Indoor Bike"],
    "Run": ["Club Run Session - Green Members"],
    "S&C": ["S&C"],
}
DEFAULT_MONTHS = 6

_CATEGORY_ORDER = {"Swim": 0, "Bike": 1, "Run": 2, "S&C": 3}
_DAY_ORDER = {"Mon": 0, "Tue": 1, "Wed": 2, "Thu": 3, "Fri": 4, "Sat": 5, "Sun": 6}


def load_attendance(data_dir: Path) -> pd.DataFrame:
    """Session headcounts joined to their category, with date parts added."""
    attendance = pd.read_csv(data_dir / "session_attendance.csv", sep="|")
    types = pd.read_csv(data_dir / "session_types.csv")

    df = attendance.merge(types, on="session_name", how="left")
    df["category"] = df["category"].fillna("Other")

    df["session_date"] = pd.to_datetime(df["session_date"])
    df["year"] = df["session_date"].dt.year
    df["month"] = df["session_date"].dt.month
    df["month_name"] = df["session_date"].dt.strftime("%b")
    df["year_month"] = df["session_date"].dt.to_period("M").astype(str)
    return df


@dataclass
class YoySummary:
    """Monthly average attendance per session/day, one column per month.

    Rows starting with "──" are category headers with empty cells. Other cells
    read "12.3  (+1.5)", the change being against the same month a year earlier,
    "12.3" when there is no prior-year figure, or "—" when the session did not
    run that month.
    """

    col_headers: list[str]
    row_labels: list[str]
    row_data: dict[str, list[str]]

    def to_frame(self) -> pd.DataFrame:
        return pd.DataFrame({"Session": self.row_labels, **self.row_data}).set_index(
            "Session"
        )


def month_window(end: tuple[int, int], num_months: int) -> list[tuple[int, int]]:
    """The (year, month) pairs for num_months months ending with end, oldest first."""
    pairs: list[tuple[int, int]] = []
    y, m = end
    for _ in range(num_months):
        pairs.append((y, m))
        m -= 1
        if m == 0:
            m = 12
            y -= 1
    pairs.reverse()
    return pairs


def yoy_summary(
    current: pd.DataFrame,
    full: pd.DataFrame,
    sessions: list[str],
    num_months: int = DEFAULT_MONTHS,
    end: tuple[int, int] | None = None,
) -> YoySummary | None:
    """Build the summary for sessions over num_months months ending with end.

    Current-period rows come from current (so a caller's filters apply), while
    prior-year comparison rows come from full (so the deltas survive a date
    filter that excludes the previous year). end defaults to the latest month
    with data for these sessions. Returns None when there is nothing to show.
    """
    sel_data = current[current["session_name"].isin(sessions)]
    if sel_data.empty:
        return None
    if end is None:
        latest = sel_data["session_date"].max()
        end = (latest.year, latest.month)

    ym_pairs = month_window(end, num_months)
    # Also need same months one year earlier for comparison
    compare_pairs = [(y - 1, m) for y, m in ym_pairs]

    cur = sel_data.copy()
    cur["ym"] = list(zip(cur["year"], cur["month"]))
    cur = cur[cur["ym"].isin(set(ym_pairs))].drop(columns="ym")

    prior = full[full["session_name"].isin(sessions)].copy()
    prior["ym"] = list(zip(prior["year"], prior["month"]))
    prior = prior[prior["ym"].isin(set(compare_pairs))].drop(columns="ym")

    src = pd.concat([cur, prior], ignore_index=True)
    if src.empty:
        return None

    # Compute monthly averages per session / day-of-week / year / month
    summary = (
        src.groupby(["year", "month", "session_name", "session_day_of_week"])[
            "attended"
        ]
        .mean()
        .reset_index()
        .rename(columns={"attended": "avg"})
    )
    summary["avg"] = summary["avg"].round(1)
    summary["label"] = (
        summary["session_name"] + " (" + summary["session_day_of_week"].str[:3] + ")"
    )

    # Map each label back to its category for ordering
    label_cat = (
        summary.drop_duplicates("label")
        .set_index("label")["session_name"]
        .map(full.drop_duplicates("session_name").set_index("session_name")["category"])
    )

    # Only keep session/day combos that exist in the current period
    # (excludes defunct sessions like Tuesday S&C that no longer run)
    active_labels = set(
        summary[summary[["year", "month"]].apply(tuple, axis=1).isin(ym_pairs)]["label"]
    )
    if not active_labels:
        return None
    summary = summary[summary["label"].isin(active_labels)]

    averages = {
        (row.label, row.year, row.month): row.avg for row in summary.itertuples()
    }

    # Column headers: "Mon YYYY" for each month in the window
    col_headers = [pd.Timestamp(y, m, 1).strftime("%b %Y") for y, m in ym_pairs]

    # Order labels: Swim → Bike → Run → S&C, then by day of week within each
    def _sort_key(lbl: str) -> tuple[int, str, int]:
        cat_idx = _CATEGORY_ORDER.get(label_cat.get(lbl, "Other"), 9)
        # Extract the 3-letter day abbreviation from "Session Name (Day)"
        day_abbr = lbl.rsplit("(", 1)[-1].rstrip(")")
        day_idx = _DAY_ORDER.get(day_abbr, 9)
        # Group by session name (everything before the day), then by day
        session_name = lbl.rsplit("(", 1)[0].strip()
        return (cat_idx, session_name, day_idx)

    # Build rows with category header rows inserted
    row_labels: list[str] = []
    row_data: dict[str, list[str]] = {col: [] for col in col_headers}
    prev_cat: str | None = None
    for label in sorted(active_labels, key=_sort_key):
        cat = label_cat.get(label, "Other")
        if cat != prev_cat:
            row_labels.append(f"── {cat} ──")
            for col in col_headers:
                row_data[col].append("")
            prev_cat = cat
        row_labels.append(label)
        for (cy, cm), (py, pm), col in zip(ym_pairs, compare_pairs, col_headers):
            c = averages.get((label, cy, cm))
            p = averages.get((label, py, pm))
            if c is not None and p is not None:
                diff = c - p
                sign = "+" if diff > 0 else ""
                row_data[col].append(f"{c:.1f}  ({sign}{diff:.1f})")
            elif c is not None:
                row_data[col].append(f"{c:.1f}")
            else:
                row_data[col].append("—")

    return YoySummary(col_headers, row_labels, row_data)


def html_table(summary: YoySummary) -> str:
    """Render the summary as an inline-styled HTML table that survives email."""
    green = "#2e7d32"
    red = "#c62828"
    grey = "#9e9e9e"
    col_headers = summary.col_headers
    html = (
        '<table style="border-collapse:collapse;font-family:Arial,sans-serif;'
        'font-size:13px">'
    )
    # Header row
    html += "<tr>"
    html += '<th style="text-align:left;padding:4px 10px;border-bottom:2px solid #333">Session</th>'
    for col in col_headers:
        html += (
            f'<th style="text-align:center;padding:4px 10px;'
            f'border-bottom:2px solid #333">{col}</th>'
        )
    html += "</tr>"
    # Data rows
    for i, label in enumerate(summary.row_labels):
        if label.startswith("──"):
            html += "<tr>"
            html += (
                f'<td colspan="{len(col_headers) + 1}" style="padding:8px 4px 2px;'
                f'font-weight:bold;font-size:14px;border-bottom:1px solid #ccc">'
                f"{label}</td>"
            )
            html += "</tr>"
            continue
        html += "<tr>"
        html += f'<td style="padding:3px 10px">{label}</td>'
        for col in col_headers:
            val = summary.row_data[col][i]
            # Colour the delta part
            cell_style = "text-align:center;padding:3px 10px"
            if "(" in val:
                main, delta = val.split("(", 1)
                delta = delta.rstrip(")")
                if delta.strip().startswith("+"):
                    colour = green
                elif delta.strip().startswith("-"):
                    colour = red
                else:
                    colour = grey
                cell_html = (
                    f"{main.strip()} "
                    f'<span style="color:{colour};font-size:11px">'
                    f"({delta})</span>"
                )
            else:
                cell_html = val
            html += f'<td style="{cell_style}">{cell_html}</td>'
        html += "</tr>"
    html += "</table>"
    return html
