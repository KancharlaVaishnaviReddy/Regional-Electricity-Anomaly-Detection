"""Streamlit dashboard: Supabase anomaly summaries plus local MW history."""

import glob
import os
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from dotenv import load_dotenv
from streamlit_autorefresh import st_autorefresh
from supabase import create_client


ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

st.set_page_config(page_title="PJM Electricity Anomalies", layout="wide")
st.title("Regional Electricity Consumption Anomalies")

# MW time series palette.
MW_OBSERVED = "#83C9FF"   # light blue (observed line)
MW_ANOMALY = "#0068C9"    # dark blue (anomaly line)
AXIS_GREY = "#7D8597"
GRID_GREY = "#E6EAF1"

# Remove the card border around the MW chart only (needs Streamlit >= 1.39).
st.markdown(
    """
    <style>
      .st-key-mw_series [data-testid="stPlotlyChart"] {
        border: none !important;
        box-shadow: none !important;
        padding: 0 !important;
        background: transparent !important;
      }
    </style>
    """,
    unsafe_allow_html=True,
)

url = os.getenv("SUPABASE_URL")
key = os.getenv("SUPABASE_ANON_KEY")
if not url or not key:
    st.error("Set SUPABASE_URL and SUPABASE_ANON_KEY in the project .env file.")
    st.stop()

refresh_seconds = int(os.getenv("DASHBOARD_REFRESH_SECONDS", "30"))
st_autorefresh(interval=refresh_seconds * 1000, key="anomaly_refresh")
client = create_client(url, key)


def build_date_ticks(start, end):
    """Weekly ticks (Mondays); the 1st of a month is labelled with the month name."""
    span_days = (end - start).days
    if span_days > 21:
        ticks = pd.date_range(start.normalize(), end, freq="W-MON")
    elif span_days > 3:
        ticks = pd.date_range(start.normalize(), end, freq="D")
    else:
        return None, None

    tickvals = list(ticks)
    ticktext = [
        t.strftime("%B") if t.day == 1 else t.strftime("%b %d")
        for t in tickvals
    ]
    return tickvals, ticktext


try:
    summary_response = client.table("anomaly_summary").select("*").execute()
    summary = pd.DataFrame(summary_response.data)
    latest_response = (
        client.table("anomalies")
        .select("id,region,ts,mw,expected_mw,z_score,severity,alerted,created_at")
        .order("ts", desc=True)
        .limit(200)
        .execute()
    )
    latest = pd.DataFrame(latest_response.data)
except Exception as exc:
    st.error(f"Could not read Supabase data: {exc}")
    st.stop()

if summary.empty:
    st.info("No anomalies are in Supabase yet. Run the pipeline after setup.")
else:
    totals = summary.groupby("region", as_index=False)["anomaly_count"].sum()
    totals = totals.sort_values("anomaly_count", ascending=False)
    c1, c2 = st.columns(2)
    with c1:
        st.subheader("Anomalies per region")
        st.bar_chart(totals.set_index("region"))
    with c2:
        st.subheader("Severity split")
        pivot = summary.pivot_table(
            index="region", columns="severity", values="anomaly_count",
            aggfunc="sum", fill_value=0,
        )
        st.bar_chart(pivot)

if latest.empty:
    st.info("No recent anomaly rows to display.")
else:
    regions = sorted(latest["region"].dropna().unique().tolist())
    region = st.selectbox("Region for MW time series", regions)

    # ------------------------------------------------------------
    # MW time series
    # ------------------------------------------------------------
    st.markdown(f"## MW time series — {region}")

    # Historical measurements are read from the local Kaggle CSV; anomalies
    # are fetched live from Supabase. Limit display to a recent sample.
    data_dir = Path(os.getenv("DATA_DIR", "data"))
    if not data_dir.is_absolute():
        data_dir = ROOT / data_dir
    candidates = glob.glob(str(data_dir / f"{region}_*.csv"))

    if candidates:
        raw = pd.read_csv(candidates[0])
        dt_col = next(c for c in raw.columns if c.lower() == "datetime")
        mw_col = next(c for c in raw.columns if c.lower() != "datetime")
        raw = raw.rename(columns={dt_col: "ts", mw_col: "mw"})
        raw["ts"] = pd.to_datetime(raw["ts"], errors="coerce")
        raw["mw"] = pd.to_numeric(raw["mw"], errors="coerce")
        raw = raw.dropna(subset=["ts", "mw"]).sort_values("ts").tail(3000)

        region_anomalies = latest[latest["region"] == region].copy()
        if not region_anomalies.empty:
            region_anomalies["ts"] = pd.to_datetime(
                region_anomalies["ts"], errors="coerce", utc=True
            ).dt.tz_convert(None)
            region_anomalies["mw"] = pd.to_numeric(
                region_anomalies["mw"], errors="coerce"
            )
            region_anomalies["expected_mw"] = pd.to_numeric(
                region_anomalies["expected_mw"], errors="coerce"
            )
            region_anomalies["z_score"] = pd.to_numeric(
                region_anomalies["z_score"], errors="coerce"
            )
            region_anomalies = region_anomalies.dropna(subset=["ts", "mw"]).sort_values("ts")

        fig = go.Figure()

        fig.add_trace(
            go.Scatter(
                x=raw["ts"],
                y=raw["mw"],
                mode="lines",
                name="Observed MW",
                legendrank=2,
                line=dict(color=MW_OBSERVED, width=2),
                hovertemplate="Observed MW: %{y:,.0f}<extra></extra>",
            )
        )

        if not region_anomalies.empty:
            fig.add_trace(
                go.Scatter(
                    x=region_anomalies["ts"],
                    y=region_anomalies["mw"],
                    mode="lines+markers",
                    name="Anomaly MW",
                    legendrank=1,
                    line=dict(color=MW_ANOMALY, width=2),
                    marker=dict(size=4, color=MW_ANOMALY),
                    customdata=region_anomalies[["expected_mw", "z_score"]],
                    hovertemplate=(
                        "Anomaly MW: %{y:,.2f}<br>"
                        "Expected MW: %{customdata[0]:,.2f}<br>"
                        "Z-score: %{customdata[1]:.2f}<extra></extra>"
                    ),
                )
            )

        axis_font = dict(color=AXIS_GREY, size=13)

        fig.update_layout(
            template="plotly_white",
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            font=axis_font,
            height=430,
            margin=dict(l=10, r=10, t=10, b=10),
            hovermode="x unified",
            legend=dict(
                orientation="h",
                x=0,
                xanchor="left",
                y=-0.12,
                yanchor="top",
                title_text="",
                font=dict(color=AXIS_GREY, size=14),
            ),
        )

        # Horizontal gridlines only, no axis titles, y-axis starts at 0.
        fig.update_yaxes(
            title_text="",
            rangemode="tozero",
            tickformat=",",
            showgrid=True,
            gridcolor=GRID_GREY,
            zeroline=False,
            showline=False,
            ticks="",
            tickfont=axis_font,
        )

        tickvals, ticktext = build_date_ticks(raw["ts"].min(), raw["ts"].max())
        fig.update_xaxes(
            title_text="",
            showgrid=False,
            zeroline=False,
            showline=False,
            ticks="",
            tickfont=axis_font,
            tickvals=tickvals,
            ticktext=ticktext,
        )

        with st.container(key="mw_series"):
            st.plotly_chart(fig, use_container_width=True)
    else:
        st.warning(f"No local CSV found for {region}; add the Kaggle CSVs under {data_dir}.")

    st.subheader("Latest anomalies")
    st.dataframe(latest, use_container_width=True, hide_index=True)

st.caption(
    f"Dashboard auto-refreshes every {refresh_seconds} seconds. "
    "Summary and anomaly records come from Supabase; the MW history chart uses local CSV data."
)