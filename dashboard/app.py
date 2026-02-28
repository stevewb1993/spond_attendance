import streamlit as st
import pandas as pd
import plotly.express as px

from pathlib import Path

DATA_DIR = Path(__file__).parent.parent / "output_data"

st.set_page_config(page_title="Bath Amphibians Attendance", layout="wide")
st.title("Bath Amphibians Attendance Dashboard")


@st.cache_data
def load_data() -> pd.DataFrame:
    attendance = pd.read_csv(DATA_DIR / "session_attendance.csv", sep="|")
    types = pd.read_csv(DATA_DIR / "session_types.csv")

    df = attendance.merge(types, on="session_name", how="left")
    df["category"] = df["category"].fillna("Other")

    df["session_date"] = pd.to_datetime(df["session_date"])
    df["year"] = df["session_date"].dt.year
    df["month"] = df["session_date"].dt.month
    df["month_name"] = df["session_date"].dt.strftime("%b")
    df["year_month"] = df["session_date"].dt.to_period("M").astype(str)
    return df


df = load_data()

# ── Sidebar filters ──────────────────────────────────────────────────────────
st.sidebar.header("Filters")

all_categories = sorted(df["category"].unique())
selected_categories = st.sidebar.multiselect(
    "Session type",
    all_categories,
    default=[c for c in all_categories if c not in ("NA", "Other")],
)

date_min = df["session_date"].min().date()
date_max = df["session_date"].max().date()
date_range = st.sidebar.date_input(
    "Session date range",
    value=(date_min, date_max),
    min_value=date_min,
    max_value=date_max,
)

month_labels = {m: pd.Timestamp(2000, m, 1).strftime("%B") for m in range(1, 13)}

# ── Apply filters ─────────────────────────────────────────────────────────────
filtered = df[df["category"].isin(selected_categories)]
if len(date_range) == 2:
    filtered = filtered[
        (filtered["session_date"].dt.date >= date_range[0])  # ty: ignore[index-out-of-bounds]
        & (filtered["session_date"].dt.date <= date_range[1])  # ty: ignore[index-out-of-bounds]
    ]

if filtered.empty:
    st.warning("No data matches the selected filters.")
    st.stop()

# ── KPI row ───────────────────────────────────────────────────────────────────
col1, col2, col3, col4 = st.columns(4)
col1.metric("Total sessions", f"{len(filtered):,}")
col2.metric("Total attendance", f"{filtered['attended'].sum():,}")
col3.metric("Avg per session", f"{filtered['attended'].mean():.1f}")
col4.metric(
    "Date range",
    f"{filtered['session_date'].min():%b %Y} – {filtered['session_date'].max():%b %Y}",
)

# ── Tab layout ────────────────────────────────────────────────────────────────
tab_monthly, tab_yoy, tab_yoy_summary, tab_detail, tab_data = st.tabs(
    ["Monthly Trends", "Year over Year", "YoY Summary", "Session Detail", "Raw Data"]
)

# ── Monthly Trends ────────────────────────────────────────────────────────────
with tab_monthly:
    monthly_session_dow = (
        filtered.groupby(
            ["year_month", "session_name", "session_day_of_week", "category"]
        )["attended"]
        .mean()
        .reset_index()
        .rename(columns={"attended": "avg_attended"})
        .sort_values("year_month")
    )
    monthly_session_dow["label"] = (
        monthly_session_dow["session_name"]
        + " ("
        + monthly_session_dow["session_day_of_week"]
        + ")"
    )

    for cat in ["Swim", "Bike", "Run", "S&C"]:
        cat_data = monthly_session_dow[monthly_session_dow["category"] == cat]
        if cat_data.empty:
            continue
        st.subheader(f"{cat} – avg attendance by month")
        available = sorted(cat_data["label"].unique())
        selected = st.multiselect(
            f"Filter {cat} sessions (leave empty for all)",
            available,
            key=f"monthly_{cat}",
        )
        if selected:
            cat_data = cat_data[cat_data["label"].isin(selected)]
        fig = px.line(
            cat_data,
            x="year_month",
            y="avg_attended",
            color="label",
            markers=True,
            labels={
                "year_month": "Month",
                "avg_attended": "Avg attendance",
                "label": "Session (Day)",
            },
        )
        fig.update_layout(xaxis_tickangle=-45, height=500, yaxis_rangemode="tozero")
        st.plotly_chart(fig, use_container_width=True)

# ── Year-over-Year ────────────────────────────────────────────────────────────
with tab_yoy:
    yoy = (
        filtered.groupby(
            ["year", "month", "session_name", "session_day_of_week", "category"]
        )["attended"]
        .mean()
        .reset_index()
        .rename(columns={"attended": "avg_attended"})
    )
    yoy["month_name"] = yoy["month"].map(month_labels)
    yoy["label"] = yoy["session_name"] + " (" + yoy["session_day_of_week"] + ")"
    yoy["year"] = yoy["year"].astype(str)
    yoy = yoy.sort_values(["year", "month"])

    # Build a light-to-dark blue palette so recent years stand out
    all_years_yoy = sorted(yoy["year"].unique())
    n_years = len(all_years_yoy)
    if n_years == 1:
        year_colors = {all_years_yoy[0]: "rgb(8,81,156)"}
    else:
        year_colors = {
            yr: f"rgb({200 - int(180 * i / (n_years - 1))}, "
            f"{210 - int(130 * i / (n_years - 1))}, "
            f"{235 - int(79 * i / (n_years - 1))})"
            for i, yr in enumerate(all_years_yoy)
        }

    for cat in ["Swim", "Bike", "Run", "S&C"]:
        cat_data = yoy[yoy["category"] == cat]
        if cat_data.empty:
            continue
        st.subheader(f"{cat} – year over year")
        available_yoy = sorted(cat_data["label"].unique())
        selected_yoy = st.multiselect(
            f"Filter {cat} sessions (leave empty for all)",
            available_yoy,
            key=f"yoy_{cat}",
        )
        if selected_yoy:
            cat_data = cat_data[cat_data["label"].isin(selected_yoy)]
        for session_label in sorted(cat_data["label"].unique()):
            subset = cat_data[cat_data["label"] == session_label]
            fig = px.line(
                subset,
                x="month_name",
                y="avg_attended",
                color="year",
                markers=True,
                title=session_label,
                labels={
                    "month_name": "Month",
                    "avg_attended": "Avg attendance",
                    "year": "Year",
                },
                category_orders={
                    "month_name": list(month_labels.values()),
                    "year": all_years_yoy,
                },
                color_discrete_map=year_colors,
            )
            fig.update_layout(height=400, yaxis_rangemode="tozero")
            st.plotly_chart(fig, use_container_width=True)

# ── YoY Summary (pivot table) ────────────────────────────────────────────────
with tab_yoy_summary:
    st.subheader("Year-over-Year Summary")

    # Work from unfiltered data so sidebar filters don't affect this tab
    yoy_src = df.copy()

    # Session selectors per category with sensible defaults
    cat_defaults: dict[str, list[str]] = {
        "Swim": ["STV Swim", "STV swim - technique"],
        "Bike": ["Indoor Bike"],
        "Run": ["Club Run Session - Green Members"],
        "S&C": ["S&C"],
    }

    selected_sessions: list[str] = []
    for cat, defaults in cat_defaults.items():
        cat_sessions = sorted(
            yoy_src.loc[yoy_src["category"] == cat, "session_name"].unique()
        )
        if not cat_sessions:
            continue
        valid_defaults = [s for s in defaults if s in cat_sessions]
        chosen = st.multiselect(
            f"{cat} sessions",
            cat_sessions,
            default=valid_defaults,
            key=f"yoy_summary_{cat}",
        )
        selected_sessions.extend(chosen)

    if not selected_sessions:
        st.info("Select at least one session above.")
        st.stop()

    # Rolling window: last N months back from the latest data point
    num_months = st.slider("Months to show", 3, 12, 6, key="yoy_summary_months")

    # Find the latest month boundary in the data for selected sessions
    sel_data = yoy_src[yoy_src["session_name"].isin(selected_sessions)]
    latest_date = sel_data["session_date"].max()
    # Build list of (year, month) pairs going back num_months from latest
    ym_pairs: list[tuple[int, int]] = []
    y, m = latest_date.year, latest_date.month
    for _ in range(num_months):
        ym_pairs.append((y, m))
        m -= 1
        if m == 0:
            m = 12
            y -= 1
    ym_pairs.reverse()

    # Also need same months one year earlier for comparison
    compare_pairs = [(y - 1, m) for y, m in ym_pairs]
    all_pairs = set(ym_pairs) | set(compare_pairs)

    # Filter to selected sessions and relevant (year, month) combos
    src = sel_data.copy()
    src["ym"] = list(zip(src["year"], src["month"]))
    src = src[src["ym"].isin(all_pairs)].drop(columns="ym")

    # Compute monthly averages per session / day-of-week / year / month
    summary = (
        src.groupby(["year", "month", "session_name", "session_day_of_week"])["attended"]
        .mean()
        .reset_index()
        .rename(columns={"attended": "avg"})
    )
    summary["avg"] = summary["avg"].round(1)
    summary["label"] = (
        summary["session_name"] + " (" + summary["session_day_of_week"].str[:3] + ")"
    )

    if summary.empty:
        st.info("No data for the selected sessions and time range.")
        st.stop()

    # Map each label back to its category for ordering
    label_cat = (
        summary.drop_duplicates("label")
        .set_index("label")["session_name"]
        .map(
            yoy_src.drop_duplicates("session_name")
            .set_index("session_name")["category"]
        )
    )

    # Only keep session/day combos that exist in the current period
    # (excludes defunct sessions like Tuesday S&C that no longer run)
    active_labels = set(
        summary[summary[["year", "month"]].apply(tuple, axis=1).isin(ym_pairs)]["label"]
    )
    if not active_labels:
        st.info("No sessions found with data in the current period.")
        st.stop()
    summary = summary[summary["label"].isin(active_labels)]

    # Column headers: "Mon YYYY" for each month in the window
    col_headers = [f"{month_labels[m][:3]} {y}" for y, m in ym_pairs]

    # Pivot helper
    def _get_val(label: str, y: int, m: int) -> float | None:
        row = summary[
            (summary["label"] == label)
            & (summary["year"] == y)
            & (summary["month"] == m)
        ]
        if row.empty:
            return None
        return row["avg"].iloc[0]

    # Order labels: Swim → Bike → Run → S&C, then by day of week within each
    cat_order = {"Swim": 0, "Bike": 1, "Run": 2, "S&C": 3}
    day_order = {"Mon": 0, "Tue": 1, "Wed": 2, "Thu": 3, "Fri": 4, "Sat": 5, "Sun": 6}

    def _sort_key(lbl: str) -> tuple[int, str, int]:
        cat_idx = cat_order.get(label_cat.get(lbl, "Other"), 9)
        # Extract the 3-letter day abbreviation from "Session Name (Day)"
        day_abbr = lbl.rsplit("(", 1)[-1].rstrip(")")
        day_idx = day_order.get(day_abbr, 9)
        # Group by session name (everything before the day), then by day
        session_name = lbl.rsplit("(", 1)[0].strip()
        return (cat_idx, session_name, day_idx)

    ordered_labels = sorted(active_labels, key=_sort_key)

    # Build rows with category header rows inserted
    row_labels: list[str] = []
    row_data: dict[str, list[str]] = {col: [] for col in col_headers}
    prev_cat: str | None = None
    for label in ordered_labels:
        cat = label_cat.get(label, "Other")
        if cat != prev_cat:
            # Insert a category header row (bold via markdown-ish caps)
            header = f"── {cat} ──"
            row_labels.append(header)
            for col in col_headers:
                row_data[col].append("")
            prev_cat = cat
        row_labels.append(label)
        for (cy, cm), (py, pm), col in zip(ym_pairs, compare_pairs, col_headers):
            c = _get_val(label, cy, cm)
            p = _get_val(label, py, pm)
            if c is not None and p is not None:
                diff = c - p
                sign = "+" if diff > 0 else ""
                row_data[col].append(f"{c:.1f}  ({sign}{diff:.1f})")
            elif c is not None:
                row_data[col].append(f"{c:.1f}")
            else:
                row_data[col].append("—")

    display_df = pd.DataFrame({"Session": row_labels, **row_data}).set_index("Session")

    st.caption(
        f"Average attendance for the last {num_months} months. "
        f"Parentheses show change vs same month one year earlier."
    )
    st.dataframe(display_df, use_container_width=True, height=min(600, 50 + 35 * len(row_labels)))

    # Build an HTML table for pasting into emails
    def _build_html_table() -> str:
        green = "#2e7d32"
        red = "#c62828"
        grey = "#9e9e9e"
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
        for i, label in enumerate(row_labels):
            is_header = label.startswith("──")
            if is_header:
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
                val = row_data[col][i]
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
                        f'{main.strip()} '
                        f'<span style="color:{colour};font-size:11px">'
                        f"({delta})</span>"
                    )
                else:
                    cell_html = val
                html += f'<td style="{cell_style}">{cell_html}</td>'
            html += "</tr>"
        html += "</table>"
        return html

    html_table = _build_html_table()

    # Use a JS-powered copy button via streamlit components
    copy_js = (
        "<textarea id='yoy_html' style='position:absolute;left:-9999px'>"
        + html_table.replace("'", "&#39;")
        + "</textarea>"
        "<button onclick=\""
        "var ta=document.getElementById('yoy_html');"
        "var blob=new Blob([ta.value],{type:'text/html'});"
        "var item=new ClipboardItem({'text/html':blob});"
        "navigator.clipboard.write([item]).then("
        "function(){this.innerText='Copied!';var b=this;setTimeout(function(){b.innerText='Copy table for email'},1500)}.bind(this)"
        ");"
        '" style="padding:6px 16px;border-radius:4px;border:1px solid #ccc;'
        'cursor:pointer;margin-top:8px;background:#f0f0f0">'
        "Copy table for email</button>"
    )
    st.components.v1.html(copy_js, height=50)

    with st.expander("Preview email table"):
        st.components.v1.html(html_table, height=40 + 30 * len(row_labels), scrolling=True)

# ── Session Detail ────────────────────────────────────────────────────────────
with tab_detail:
    st.subheader("Session-level detail")

    detail = (
        filtered.groupby(["session_name", "category", "session_day_of_week"])[
            "attended"
        ]
        .agg(["mean", "sum", "count", "max", "min"])
        .reset_index()
        .rename(
            columns={
                "mean": "avg_attended",
                "sum": "total_attended",
                "count": "num_sessions",
                "max": "max_attended",
                "min": "min_attended",
            }
        )
        .sort_values("total_attended", ascending=False)
    )
    detail["avg_attended"] = detail["avg_attended"].round(1)

    st.dataframe(detail, use_container_width=True, hide_index=True)

# ── Raw Data ─────────────────────────────────────────────────────────────────
with tab_data:
    st.subheader("Raw data")
    raw = filtered.sort_values("session_date", ascending=False).reset_index(drop=True)
    st.dataframe(raw, use_container_width=True, hide_index=True, height=700)
