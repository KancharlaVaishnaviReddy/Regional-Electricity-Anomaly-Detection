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
      .st-key-mw_waveform_chart [data-testid="stPlotlyChart"] {{
        border: none !important;
        border-radius: 0 !important;
        padding: 0 !important;
        background: transparent !important;
        box-shadow: none !important;
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
# Report-style summary charts
# ------------------------------------------------------------

summary_region_col, summary_severity_col = st.columns(2)

with summary_region_col:
    st.subheader("Anomalies per Region")

    region_counts = (
        filtered.groupby("region")
        .size()
        .reset_index(name="Anomaly records")
        .sort_values("Anomaly records", ascending=False)
    )

    region_fig = px.bar(
        region_counts,
        x="region",
        y="Anomaly records",
        color_discrete_sequence=[BLUE],
        labels={
            "region": "Region",
            "Anomaly records": "Anomaly records",
        },
    )
    region_fig.update_layout(
        template="plotly_white",
        paper_bgcolor="#FFFFFF",
        plot_bgcolor="#FFFFFF",
        font=dict(color="#334155"),
        height=360,
        margin=dict(l=10, r=10, t=20, b=10),
        xaxis_title="Region",
        yaxis_title="Anomaly records",
    )
    st.plotly_chart(region_fig, use_container_width=True)

with summary_severity_col:
    st.subheader("Severity Split by Region")

    severity_by_region = (
        filtered.groupby(["region", "severity"])
        .size()
        .reset_index(name="Anomaly records")
    )

    severity_fig = px.bar(
        severity_by_region,
        x="region",
        y="Anomaly records",
        color="severity",
        barmode="stack",
        category_orders={"severity": ["WARNING", "CRITICAL"]},
        color_discrete_map={
            "WARNING": BLUE_MID,
            "CRITICAL": BLUE_DARK,
        },
        labels={
            "region": "Region",
            "Anomaly records": "Anomaly records",
            "severity": "Severity",
        },
    )
    severity_fig.update_layout(
        template="plotly_white",
        paper_bgcolor="#FFFFFF",
        plot_bgcolor="#FFFFFF",
        font=dict(color="#334155"),
        height=360,
        margin=dict(l=10, r=10, t=20, b=10),
        xaxis_title="Region",
        yaxis_title="Anomaly records",
        legend_title="Severity",
    )
    st.plotly_chart(severity_fig, use_container_width=True)


# ------------------------------------------------------------
# Regional electricity-consumption trend
# ------------------------------------------------------------

st.subheader("MW Time Series")
chart_regions = sorted(filtered["region"].dropna().unique().tolist())
if selected_region != "All regions":
    trend_region = selected_region
else:
    default_region_index = chart_regions.index("AEP") if "AEP" in chart_regions else 0
    trend_region = st.selectbox(
        "Region for MW time series",
        chart_regions,
        index=default_region_index,
        key="trend_region",
    )

region_flags = (
    filtered[filtered["region"] == trend_region]
    .copy()
    .sort_values("ts")
)
region_critical = int((region_flags["severity"] == "CRITICAL").sum())
region_warnings = int((region_flags["severity"] == "WARNING").sum())
st.caption(
    f"{trend_region}: {region_critical:,} critical and "
    f"{region_warnings:,} warning anomalies in the selected filters. "
    "Use the sidebar date range to view the period you need, such as April–July."
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
        mw_col = next((col for col in raw.columns if col != date_col), None)

        if date_col is None or mw_col is None:
            st.warning(
                f"Could not identify the timestamp and MW columns in "
                f"{Path(candidates[0]).name}."
            )
        else:
            history = raw.rename(columns={date_col: "ts", mw_col: "mw"})
            history["ts"] = pd.to_datetime(history["ts"], errors="coerce")
            history["mw"] = pd.to_numeric(history["mw"], errors="coerce")
            history = history.dropna(subset=["ts", "mw"])
            history = history[
                (history["ts"].dt.date >= start_date)
                & (history["ts"].dt.date <= end_date)
            ].sort_values("ts").tail(5000)

            if history.empty:
                st.info("No hourly consumption readings match this date range.")
            else:
                # Break the anomaly line across long gaps so it only appears
                # where a run of flagged hourly readings exists.
                anomaly_x = []
                anomaly_y = []
                valid_flags = region_flags.dropna(subset=["mw"]).copy()
                previous_time = None
                for _, point in valid_flags.iterrows():
                    current_time = point["ts"]
                    if (
                        previous_time is not None
                        and current_time - previous_time > pd.Timedelta(hours=1.5)
                    ):
                        anomaly_x.append(None)
                        anomaly_y.append(None)
                    anomaly_x.append(current_time)
                    anomaly_y.append(point["mw"])
                    previous_time = current_time

                fig = go.Figure()
                # Draw the observed line first so the anomaly segment remains visible on top.
                fig.add_trace(
                    go.Scatter(
                        x=history["ts"],
                        y=history["mw"],
                        mode="lines",
                        name="Observed MW",
                        legendrank=1,
                        line=dict(color="#83C9FF", width=2),
                        hovertemplate=(
                            "Time: %{x|%b %d, %Y %H:%M}<br>"
                            "Observed MW: %{y:,.0f}<extra></extra>"
                        ),
                    )
                )
                if anomaly_x:
                    fig.add_trace(
                        go.Scatter(
                            x=anomaly_x,
                            y=anomaly_y,
                            mode="lines",
                            name="Anomaly MW",
                            legendrank=0,
                            connectgaps=False,
                            line=dict(color="#0068C9", width=2),
                            hovertemplate=(
                                "Flagged reading<br>"
                                "Time: %{x|%b %d, %Y %H:%M}<br>"
                                "Anomaly MW: %{y:,.0f}<extra></extra>"
                            ),
                        )
                    )

                first_day = history["ts"].min().normalize()
                last_day = history["ts"].max().normalize()
                monday_ticks = set(
                    pd.date_range(first_day, last_day, freq="W-MON").to_list()
                )
                month_start = first_day.replace(day=1)
                month_ticks = set(
                    pd.date_range(month_start, last_day, freq="MS").to_list()
                )
                tick_days = sorted(monday_ticks | month_ticks)
                tick_days = [
                    day for day in tick_days
                    if first_day <= day <= last_day
                ]
                tick_labels = [
                    day.strftime("%B") if day.day == 1 else day.strftime("%b %d")
                    for day in tick_days
                ]

                data_max = float(history["mw"].max())
                y_top = max(5000, int(((data_max * 1.03 + 4999) // 5000) * 5000))
                y_ticks = list(range(0, y_top, 5000))

                fig.update_layout(
                    template="plotly_white",
                    paper_bgcolor="rgba(0,0,0,0)",
                    plot_bgcolor="rgba(0,0,0,0)",
                    font=dict(
                        family="Source Sans 3, Source Sans Pro, Arial, sans-serif",
                        color="#7D8597",
                    ),
                    height=340,
                    margin=dict(l=55, r=12, t=8, b=68),
                    hovermode="x",
                    legend=dict(
                        orientation="h",
                        yanchor="top",
                        y=-0.23,
                        xanchor="left",
                        x=0,
                        traceorder="normal",
                        font=dict(color="#7D8597"),
                    ),
                )
                fig.update_xaxes(
                    title=None,
                    tickmode="array",
                    tickvals=tick_days,
                    ticktext=tick_labels,
                    showgrid=False,
                    showline=False,
                    ticks="",
                    ticklen=0,
                    zeroline=False,
                    tickfont=dict(color="#7D8597"),
                    range=[history["ts"].min(), history["ts"].max()],
                )
                fig.update_yaxes(
                    title=None,
                    range=[0, y_top],
                    tickmode="array",
                    tickvals=y_ticks,
                    tickformat=",.0f",
                    showgrid=True,
                    gridcolor="#E5E7EB",
                    gridwidth=1,
                    showline=False,
                    ticks="",
                    ticklen=0,
                    zeroline=False,
                    tickfont=dict(color="#7D8597"),
                )

                # Scoped container class allows this chart to stay borderless
                # while the other dashboard charts retain their card borders.
                with st.container(key="mw_waveform_chart"):
                    st.plotly_chart(
                        fig,
                        use_container_width=True,
                        config={"displayModeBar": False},
                    )

    except Exception as exc:
        st.error(f"Could not read the regional CSV: {exc}")


# ------------------------------------------------------------
# Anomaly event markers and email status
# ------------------------------------------------------------

st.subheader("Anomaly Events and Email Status")

plot_flags = region_flags.dropna(subset=["ts", "mw"]).copy()

if plot_flags.empty:
    st.info("No anomaly records match the selected region and filters.")
else:
    plot_flags["Email marked sent"] = plot_flags["alerted"].fillna(False).astype(bool)
    plot_flags["Plot group"] = plot_flags.apply(
        lambda row: (
            "Email marked sent"
            if row["Email marked sent"]
            else f"{row['severity']} — not marked sent"
        ),
        axis=1,
    )

    marker_styles = {
        "WARNING — not marked sent": {
            "color": BLUE_MID,
            "symbol": "circle",
            "size": 9,
        },
        "CRITICAL — not marked sent": {
            "color": BLUE_DARK,
            "symbol": "diamond",
            "size": 10,
        },
        "Email marked sent": {
            "color": "#16A34A",
            "symbol": "star",
            "size": 15,
        },
    }

    anomaly_fig = go.Figure()
    for label, style in marker_styles.items():
        points = plot_flags[plot_flags["Plot group"] == label]
        if points.empty:
            continue

        anomaly_fig.add_trace(
            go.Scatter(
                x=points["ts"],
                y=points["mw"],
                mode="markers",
                name=label,
                marker={
                    "color": style["color"],
                    "symbol": style["symbol"],
                    "size": style["size"],
                    "line": {"color": "white", "width": 1},
                },
                customdata=points[
                    ["severity", "expected_mw", "z_score"]
                ].to_numpy(),
                hovertemplate=(
                    "Time: %{x|%b %d, %Y %H:%M}<br>"
                    "Observed MW: %{y:,.0f}<br>"
                    "Severity: %{customdata[0]}<br>"
                    "Expected MW: %{customdata[1]:,.0f}<br>"
                    "Z-score: %{customdata[2]:.2f}<extra></extra>"
                ),
            )
        )

    anomaly_fig.update_layout(
        template="plotly_white",
        paper_bgcolor="#FFFFFF",
        plot_bgcolor="#FFFFFF",
        font=dict(color="#334155"),
        height=370,
        margin=dict(l=10, r=10, t=20, b=10),
        xaxis_title="Date and time",
        yaxis_title="Observed consumption (MW)",
        hovermode="closest",
        legend_title="Anomaly status",
    )
    anomaly_fig.update_xaxes(showgrid=False)
    anomaly_fig.update_yaxes(gridcolor="#E7EEF7")
    st.plotly_chart(anomaly_fig, use_container_width=True)

    st.caption(
        "A green star means the record is marked as alerted in Supabase. "
        "It shows the function updated the alert flag; confirm delivery "
        "in the recipient inbox or Resend."
    )


# ------------------------------------------------------------
# Anomaly pattern by hour
# ------------------------------------------------------------

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
    height=max(340, 35 * len(heat)),
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
