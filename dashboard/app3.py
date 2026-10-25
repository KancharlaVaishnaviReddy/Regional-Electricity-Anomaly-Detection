"""Streamlit dashboard for PJM electricity anomalies."""

import glob
import os
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import requests
import streamlit as st
from dotenv import load_dotenv
from streamlit_autorefresh import st_autorefresh
from supabase import create_client


# ------------------------------------------------------------
# Configuration
# ------------------------------------------------------------

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

st.set_page_config(
    page_title="PJM Electricity Anomalies",
    page_icon="⚡",
    layout="wide",
)

url = os.getenv("SUPABASE_URL")
key = os.getenv("SUPABASE_ANON_KEY")

if not url or not key:
    st.error("Set SUPABASE_URL and SUPABASE_ANON_KEY in your project .env file.")
    st.stop()

try:
    refresh_seconds = max(10, int(os.getenv("DASHBOARD_REFRESH_SECONDS", "30")))
except ValueError:
    refresh_seconds = 30

st_autorefresh(interval=refresh_seconds * 1000, key="anomaly_refresh")
client = create_client(url, key)

# Display up to this many recent records for filtering and charts.
MAX_RECORDS = 5000
PAGE_SIZE = 1000

# Blue palette used consistently across every dashboard chart.
BLUE = "#2563EB"
BLUE_DARK = "#1D4ED8"
BLUE_MID = "#60A5FA"
BLUE_LIGHT = "#BFDBFE"
CHART_BORDER = "#C8D6E8"


# ------------------------------------------------------------
# Styling
# ------------------------------------------------------------

st.markdown(
    f"""
    <style>
      .block-container {{
        padding-top: 1.1rem;
        padding-bottom: 2rem;
      }}
      [data-testid="stMetric"] {{
        background: #F4F8FF;
        border: 1px solid #C8D6E8;
        border-left: 4px solid {BLUE};
        padding: 14px 16px;
        border-radius: 10px;
      }}
      [data-testid="stMetricLabel"] {{
        color: #526174;
      }}
      /* A separate bordered card around each Plotly chart. */
      [data-testid="stPlotlyChart"] {{
        border: 1px solid {CHART_BORDER} !important;
        border-radius: 10px;
        padding: 8px;
        background: #FFFFFF;
        box-shadow: 0 1px 3px rgba(15, 45, 80, 0.06);
      }}
      h1, h2, h3 {{
        color: #18324B;
      }}
    </style>
    """,
    unsafe_allow_html=True,
)


# ------------------------------------------------------------
# Load records from Supabase
# ------------------------------------------------------------

@st.cache_data(ttl=30, show_spinner=False)
def load_anomalies():
    rows = []
    start = 0
    select_columns = (
        "id,region,ts,mw,expected_mw,z_score,"
        "severity,alerted,created_at"
    )

    while start < MAX_RECORDS:
        end = min(start + PAGE_SIZE - 1, MAX_RECORDS - 1)

        response = (
            client.table("anomalies")
            .select(select_columns)
            .order("ts", desc=True)
            .range(start, end)
            .execute()
        )

        page = response.data or []
        rows.extend(page)

        if len(page) < PAGE_SIZE:
            break

        start += PAGE_SIZE

    df = pd.DataFrame(rows)

    if df.empty:
        return df

    df["region"] = df["region"].fillna("Unknown").astype(str)
    df["severity"] = (
        df["severity"].fillna("UNKNOWN").astype(str).str.upper()
    )

    for column in ["mw", "expected_mw", "z_score"]:
        df[column] = pd.to_numeric(df[column], errors="coerce")

    df["ts"] = pd.to_datetime(df["ts"], errors="coerce", utc=True)
    df["ts"] = df["ts"].dt.tz_convert(None)

    df["created_at"] = pd.to_datetime(
        df["created_at"], errors="coerce", utc=True
    ).dt.tz_convert(None)

    df["alerted"] = (
        df["alerted"]
        .fillna(False)
        .astype(str)
        .str.lower()
        .isin(["true", "1", "yes"])
    )

    return df.dropna(subset=["ts"]).copy()


try:
    with st.spinner("Loading anomaly records..."):
        anomalies = load_anomalies()
except Exception as exc:
    st.error(f"Could not read anomaly records from Supabase: {exc}")
    st.stop()

if anomalies.empty:
    st.title("Regional Electricity Consumption Anomalies")
    st.info("No anomaly records were returned. Run your pipeline, then refresh.")
    st.stop()


# ------------------------------------------------------------
# Header and filters
# ------------------------------------------------------------

header, refresh_col = st.columns([5, 1])

with header:
    st.title("Electricity Anomaly Overview")
    st.caption(
        "Regional consumption patterns, statistical anomaly flags, "
        "and critical email-alert status"
    )

with refresh_col:
    st.write("")
    if st.button("Refresh", use_container_width=True):
        load_anomalies.clear()
        st.rerun()

st.sidebar.header("Dashboard Filters")

available_regions = sorted(anomalies["region"].dropna().unique().tolist())
available_severities = sorted(
    anomalies["severity"].dropna().unique().tolist()
)

selected_region = st.sidebar.selectbox(
    "Region",
    ["All regions"] + available_regions,
)

selected_severities = st.sidebar.multiselect(
    "Severity",
    available_severities,
    default=available_severities,
)

min_date = anomalies["ts"].min().date()
max_date = anomalies["ts"].max().date()

date_selection = st.sidebar.date_input(
    "Date range",
    value=(min_date, max_date),
    min_value=min_date,
    max_value=max_date,
)

if isinstance(date_selection, (tuple, list)) and len(date_selection) == 2:
    start_date, end_date = date_selection
else:
    start_date = end_date = date_selection

if start_date > end_date:
    start_date, end_date = end_date, start_date

filtered = anomalies[
    (anomalies["ts"].dt.date >= start_date)
    & (anomalies["ts"].dt.date <= end_date)
    & (anomalies["severity"].isin(selected_severities))
].copy()

if selected_region != "All regions":
    filtered = filtered[filtered["region"] == selected_region]

st.caption(
    f"Showing {len(filtered):,} matching records from the latest "
    f"{len(anomalies):,} records loaded from Supabase. "
    f"Dashboard refreshes every {refresh_seconds} seconds."
)

if filtered.empty:
    st.warning("No records match the selected filters.")
    st.stop()


# ------------------------------------------------------------
# KPI cards
# ------------------------------------------------------------

critical = filtered[filtered["severity"] == "CRITICAL"]
warnings = filtered[filtered["severity"] == "WARNING"]
marked_sent = int(critical["alerted"].sum())
email_pending = max(0, len(critical) - marked_sent)

k1, k2, k3, k4 = st.columns(4)
k1.metric("Anomaly records", f"{len(filtered):,}")
k2.metric("Critical anomalies", f"{len(critical):,}")
k3.metric("Warnings", f"{len(warnings):,}")
k4.metric("Critical alerts marked sent", f"{marked_sent:,}")

st.divider()


# ------------------------------------------------------------
# Charts: consumption trend and severity split
# ------------------------------------------------------------

trend_col, severity_col = st.columns([1.6, 1])

with trend_col:
    st.subheader("Consumption Trend")

    chart_regions = sorted(filtered["region"].dropna().unique().tolist())
    if selected_region != "All regions":
        trend_region = selected_region
    else:
        trend_region = st.selectbox(
            "Region for trend chart",
            chart_regions,
            key="trend_region",
        )

    data_dir = Path(os.getenv("DATA_DIR", "data"))
    if not data_dir.is_absolute():
        data_dir = ROOT / data_dir

    candidates = glob.glob(str(data_dir / f"{trend_region}_*.csv"))

    if not candidates:
        st.warning(
            f"No local CSV found for {trend_region}. "
            f"Check the files under {data_dir}."
        )
    else:
        try:
            raw = pd.read_csv(candidates[0])

            date_col = next(
                (
                    col for col in raw.columns
                    if col.lower() in {"datetime", "timestamp", "ts", "date"}
                ),
                None,
            )
            mw_col = next(
                (col for col in raw.columns if col != date_col),
                None,
            )

            if date_col is None or mw_col is None:
                st.warning(
                    f"Could not identify the timestamp and MW columns in "
                    f"{Path(candidates[0]).name}."
                )
            else:
                history = raw.rename(
                    columns={date_col: "ts", mw_col: "mw"}
                )
                history["ts"] = pd.to_datetime(
                    history["ts"], errors="coerce"
                )
                history["mw"] = pd.to_numeric(
                    history["mw"], errors="coerce"
                )
                history = history.dropna(subset=["ts", "mw"])
                history = history[
                    (history["ts"].dt.date >= start_date)
                    & (history["ts"].dt.date <= end_date)
                ].sort_values("ts").tail(5000)

                trend_flags = filtered[
                    filtered["region"] == trend_region
                ].copy()

                fig = go.Figure()

                if not history.empty:
                    fig.add_trace(
                        go.Scatter(
                            x=history["ts"],
                            y=history["mw"],
                            mode="lines",
                            name="Observed MW",
                            line=dict(color=BLUE, width=1.8),
                        )
                    )

                for severity, color in [
                    ("WARNING", BLUE_MID),
                    ("CRITICAL", BLUE_DARK),
                ]:
                    points = trend_flags[
                        trend_flags["severity"] == severity
                    ]

                    if not points.empty:
                        fig.add_trace(
                            go.Scatter(
                                x=points["ts"],
                                y=points["mw"],
                                mode="markers",
                                name=f"{severity} anomaly",
                                marker=dict(color=color, size=8),
                                customdata=points[
                                    ["expected_mw", "z_score"]
                                ],
                                hovertemplate=(
                                    "Time: %{x}<br>"
                                    "Observed MW: %{y:,.2f}<br>"
                                    "Expected MW: %{customdata[0]:,.2f}<br>"
                                    "Z-score: %{customdata[1]:.2f}"
                                    "<extra></extra>"
                                ),
                            )
                        )

                fig.update_layout(
                    template="plotly_white",
                    paper_bgcolor="#FFFFFF",
                    plot_bgcolor="#FFFFFF",
                    font=dict(color="#334155"),
                    height=390,
                    margin=dict(l=10, r=10, t=20, b=10),
                    xaxis_title="Date and time",
                    yaxis_title="Electricity consumption (MW)",
                    hovermode="x unified",
                    legend_title="",
                )
                st.plotly_chart(fig, use_container_width=True)

                st.caption(
                    "Expected MW and z-score appear in the hover details "
                    "for flagged readings."
                )

        except Exception as exc:
            st.error(f"Could not read the regional CSV: {exc}")


with severity_col:
    st.subheader("Severity Split")

    severity_counts = (
        filtered.groupby("severity")
        .size()
        .reset_index(name="count")
    )

    severity_fig = px.pie(
        severity_counts,
        names="severity",
        values="count",
        hole=0.58,
        color="severity",
        color_discrete_map={
            "WARNING": BLUE_MID,
            "CRITICAL": BLUE_DARK,
        },
    )
    severity_fig.update_layout(
        template="plotly_white",
        paper_bgcolor="#FFFFFF",
        plot_bgcolor="#FFFFFF",
        font=dict(color="#334155"),
        height=390,
        margin=dict(l=10, r=10, t=20, b=10),
        legend_title="Severity",
    )
    st.plotly_chart(severity_fig, use_container_width=True)


# ------------------------------------------------------------
# Lower dashboard charts
# ------------------------------------------------------------

region_col, hour_col = st.columns([1, 1.4])

with region_col:
    st.subheader("Anomalies by Region")

    region_counts = (
        filtered.groupby(["region", "severity"])
        .size()
        .reset_index(name="count")
    )

    region_fig = px.bar(
        region_counts,
        x="count",
        y="region",
        color="severity",
        orientation="h",
        barmode="stack",
        color_discrete_map={
            "WARNING": BLUE_MID,
            "CRITICAL": BLUE_DARK,
        },
        labels={
            "region": "Region",
            "count": "Anomaly records",
            "severity": "Severity",
        },
    )
    region_fig.update_layout(
        template="plotly_white",
        paper_bgcolor="#FFFFFF",
        plot_bgcolor="#FFFFFF",
        font=dict(color="#334155"),
        height=360,
        margin=dict(l=10, r=10, t=20, b=10),
        yaxis={"categoryorder": "total ascending"},
    )
    st.plotly_chart(region_fig, use_container_width=True)

with hour_col:
    st.subheader("Anomaly Pattern by Hour")

    hourly = filtered.copy()
    hourly["hour"] = hourly["ts"].dt.hour

    heat = hourly.pivot_table(
        index="region",
        columns="hour",
        values="ts",
        aggfunc="count",
        fill_value=0,
    ).reindex(columns=list(range(24)), fill_value=0)

    heat_fig = px.imshow(
        heat,
        aspect="auto",
        color_continuous_scale="Blues",
        labels={
            "x": "Hour of day",
            "y": "Region",
            "color": "Anomalies",
        },
    )
    heat_fig.update_layout(
        template="plotly_white",
        paper_bgcolor="#FFFFFF",
        plot_bgcolor="#FFFFFF",
        font=dict(color="#334155"),
        height=360,
        margin=dict(l=10, r=10, t=20, b=10),
    )
    st.plotly_chart(heat_fig, use_container_width=True)


# ------------------------------------------------------------
# Latest anomaly table and manual email option
# ------------------------------------------------------------

st.divider()
st.subheader("Latest Anomalies")

table_col, email_col = st.columns([3, 1])

display_df = filtered.sort_values("ts", ascending=False).rename(
    columns={
        "id": "ID",
        "region": "Region",
        "ts": "Timestamp",
        "mw": "Observed MW",
        "expected_mw": "Expected MW",
        "z_score": "Z-score",
        "severity": "Severity",
        "alerted": "Email marked sent",
        "created_at": "Created at",
    }
)

with table_col:
    st.dataframe(
        display_df,
        use_container_width=True,
        hide_index=True,
    )

with email_col:
    st.markdown("#### Manual email")

    critical_rows = filtered[
        filtered["severity"] == "CRITICAL"
    ].copy()

    if critical_rows.empty:
        st.info("No critical anomalies in the current filter.")
    else:
        critical_rows["id_text"] = critical_rows["id"].astype(str)

        selected_id = st.selectbox(
            "Select a critical anomaly",
            critical_rows["id_text"].tolist(),
            format_func=lambda anomaly_id: (
                f"{critical_rows.loc[critical_rows['id_text'] == anomaly_id, 'region'].iloc[0]} — "
                f"{critical_rows.loc[critical_rows['id_text'] == anomaly_id, 'ts'].iloc[0]}"
            ),
        )

        st.warning(
            "Only use this for a test or intentional resend. "
            "It can send a real email."
        )

        confirm_send = st.checkbox(
            "I confirm that I want to send this email."
        )

        if st.button(
            "Send email",
            type="primary",
            use_container_width=True,
            disabled=not confirm_send,
        ):
            manual_secret = os.getenv("MANUAL_ALERT_SECRET")

            if not manual_secret:
                st.error(
                    "Add MANUAL_ALERT_SECRET to your local .env file "
                    "and as a Supabase Edge Function secret."
                )
            else:
                function_url = (
                    f"{url.rstrip('/')}/functions/v1/alert"
                )

                try:
                    response = requests.post(
                        function_url,
                        headers={
                            "apikey": key,
                            "Authorization": f"Bearer {key}",
                            "Content-Type": "application/json",
                            "x-manual-alert-secret": manual_secret,
                        },
                        json={
                            "action": "manual_send",
                            "anomaly_id": selected_id,
                        },
                        timeout=20,
                    )

                    try:
                        result = response.json()
                    except ValueError:
                        result = {}

                    if response.ok and result.get("success") is True:
                        st.success(
                            "The function accepted the request. "
                            "Check the recipient inbox and Resend logs."
                        )
                    else:
                        st.error(
                            result.get(
                                "error",
                                f"Request failed with HTTP {response.status_code}.",
                            )
                        )

                except requests.RequestException as exc:
                    st.error(f"Could not reach the email function: {exc}")

st.caption(
    "Anomaly flags are statistical results for review, not proof of an outage "
    "or its cause. Email status is based on the database alert flag."
)
