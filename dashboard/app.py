import sys

import streamlit as st
import pandas as pd
import plotly.express as px

from pathlib import Path

# Streamlit Cloud runs this script without installing the package, so find it
# in the repo's src/ directory.
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from spond_attendance.summary import (  # noqa: E402
    DEFAULT_MONTHS,
    DEFAULT_SESSIONS,
    load_attendance,
    yoy_summary,
)
from spond_attendance.summary import html_table as html_table_for  # noqa: E402

DATA_DIR = Path(__file__).parent.parent / "output_data"

st.set_page_config(page_title="Bath Amphibians Attendance", layout="wide")
st.title("Bath Amphibians Attendance Dashboard")


@st.cache_data
def load_data() -> pd.DataFrame:
    return load_attendance(DATA_DIR)


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

    # Respect the sidebar filters (category + date range) for which sessions and
    # months are displayed. The year-over-year comparison values are pulled from
    # the full dataset (yoy_full) so the deltas still work even when the date
    # range excludes the prior year.
    yoy_src = filtered.copy()
    yoy_full = df.copy()

    selected_sessions: list[str] = []
    for cat, defaults in DEFAULT_SESSIONS.items():
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
    num_months = st.slider(
        "Months to show", 3, 12, DEFAULT_MONTHS, key="yoy_summary_months"
    )

    yoy_table = yoy_summary(yoy_src, yoy_full, selected_sessions, num_months)
    if yoy_table is None:
        st.info("No data for the selected sessions and time range.")
        st.stop()
    assert yoy_table is not None  # st.stop() ends the script run
    row_labels = yoy_table.row_labels

    st.caption(
        f"Average attendance for the last {num_months} months. "
        f"Parentheses show change vs same month one year earlier."
    )
    st.dataframe(
        yoy_table.to_frame(),
        use_container_width=True,
        height=min(600, 50 + 35 * len(row_labels)),
    )

    html_table = html_table_for(yoy_table)

    # Use a JS-powered copy button via streamlit components.
    # We render the HTML in a hidden div and use execCommand('copy') on the
    # selected contents — this copies as rich text (ideal for email) and works
    # inside Streamlit's sandboxed iframe where the Clipboard API is blocked.
    escaped_html = html_table.replace("\\", "\\\\").replace("`", "\\`")
    copy_js = (
        f"<div id='yoy_render' style='position:fixed;left:-9999px'>{html_table}</div>"
        '<button onclick="'
        "var div=document.getElementById('yoy_render');"
        "var range=document.createRange();"
        "range.selectNodeContents(div);"
        "var sel=window.getSelection();"
        "sel.removeAllRanges();"
        "sel.addRange(range);"
        "document.execCommand('copy');"
        "sel.removeAllRanges();"
        "this.innerText='Copied!';"
        "var b=this;setTimeout(function(){b.innerText='Copy table for email'},1500);"
        '" style="padding:6px 16px;border-radius:4px;border:1px solid #ccc;'
        'cursor:pointer;margin-top:8px;background:#f0f0f0">'
        "Copy table for email</button>"
    )
    st.components.v1.html(copy_js, height=50)

    with st.expander("Preview email table"):
        st.components.v1.html(
            html_table, height=40 + 30 * len(row_labels), scrolling=True
        )

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
