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
tab_monthly, tab_yoy, tab_detail, tab_data = st.tabs(
    ["Monthly Trends", "Year over Year", "Session Detail", "Raw Data"]
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
