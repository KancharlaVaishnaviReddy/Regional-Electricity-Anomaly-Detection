# ⚡ Anomaly Detection in Regional Electricity Consumption

An end-to-end big-data pipeline that screens hourly regional electricity consumption (PJM) for statistically unusual readings using PySpark, stores the flags in Supabase Postgres, emails critical alerts, and visualizes everything in a Streamlit dashboard.

---

## 📊 Project Overview

This project uses the PJM Hourly Energy Consumption dataset to find unusual spikes and drops in hourly demand across many regional series. It covers the full workflow: ingestion, cleaning, feature engineering, anomaly detection, database storage, email alerting and visualization.

**Pipeline Flow:**

```
Kaggle CSVs → PySpark Cleaning → Feature Engineering → Contextual Z-Score Detector
        → Supabase Postgres → Database Webhook → Edge Function → Resend Email
                         └──────────────→ Streamlit Dashboard
```

> ⚠️ Flagged readings are statistical outliers only. They are not verified faults, outages or causes.

## 🎯 Key Features

- **Distributed-style processing:** PySpark DataFrames with a modular pipeline
- **Data cleaning:** timestamp parsing, null/non-positive/duplicate removal, with printed row counts at every step
- **Feature engineering:** hour, day-of-week, weekend flag and month
- **Two detectors:**
  - Contextual z-score (region + hour + weekend + month), the primary detector
  - 168-hour rolling window, used for comparison
- **Idempotent storage:** unique `(region, ts)` key, so reruns never create duplicates
- **Automatic critical alerts:** Database Webhook → Edge Function → Resend email
- **Interactive dashboard:** filters, summary cards, charts, email status and a manual email control

## 📈 Dataset

**Source:** [Hourly Energy Consumption (PJM) by Robikscube on Kaggle](https://www.kaggle.com/datasets/robikscube/hourly-energy-consumption)

- Separate hourly CSV files for series such as AEP, COMED, DAYTON, DEOK, DOM, DUQ, EKPC, FE, NI, PJME and PJMW
- The combined `PJM_Load` estimate file is excluded, per the project specification
- Series names are identifiers, not necessarily geographic service territories

## 🚀 Quick Start

### Prerequisites

- Python 3.10+
- Java (required by Spark)
- A Supabase project and a Resend account
- `pip install -r requirements.txt`

### Installation

1. **Clone the repository**
   ```bash
   git clone https://github.com/KancharlaVaishnaviReddy/<repo-name>.git
   cd <repo-name>
   ```

2. **Download the dataset**
   - Download the PJM CSV files from Kaggle
   - Place them in the `data/` folder

3. **Configure environment variables**
   ```bash
   cp .env.example .env
   ```
   Fill in your Supabase and Resend values. Never commit `.env`.

4. **Set up Supabase**
   - Run `sql/schema.sql` in the Supabase SQL editor
   - Deploy the alert function:
     ```bash
     npx supabase functions deploy alert --project-ref <PROJECT_REF> --no-verify-jwt
     ```
   - Create a Database Webhook on `INSERT` for `public.anomalies` pointing to the `alert` function

5. **Run the pipeline**
   ```bash
   # Quick test without database writes
   python src/main.py --regions AEP,COMED --no-write

   # Selected regions, with database write
   python src/main.py --regions AEP,COMED

   # Full dataset
   python src/main.py
   ```

6. **Launch the dashboard**
   ```bash
   streamlit run dashboard/app.py
   ```

It also runs in **Google Colab**: keep the project and CSVs in Drive, install Java and the Python packages, mount Drive, load secrets from Colab Secrets and run the same entry point.

## 📋 Project Structure

```
electricity-anomaly/
├── README.md
├── src/
│   ├── config.py             # Env-based paths and DB settings
│   ├── ingest.py             # CSV discovery and union
│   ├── clean.py              # Type casting and filtering
│   ├── features.py           # Calendar features
│   ├── detect_zscore.py      # Contextual detector
│   ├── detect_rolling.py     # 168-hour rolling detector
│   ├── write_supabase.py     # JDBC staging + conflict-safe merge
│   └── main.py               # Pipeline driver
├── data/                     # PJM CSV files (gitignored)
├── sql/schema.sql            # Database schema
├── supabase/functions/alert/index.ts   # Alert Edge Function
├── dashboard/app.py          # Streamlit dashboard
├── notebooks/analysis.ipynb  # Analysis and event-window screening
├── artifacts/                # Parquet outputs and plots
└── .env.example              # Variable names only, no secrets
```

## 🔬 Pipeline Stages

### 1. Ingestion
- Discover regional CSVs under `data/` and exclude the combined estimate file
- Rename the datetime and measurement columns to `raw_ts` and `raw_mw`, add the region and union by column name

### 2. Cleaning
- Convert timestamps and cast MW to double
- Remove null, unparseable and non-positive rows
- Drop duplicate `(region, ts)` pairs

### 3. Feature Engineering
- Hour of day, day of week, weekend flag and month

### 4. Contextual Z-Score Detection (primary)
- Mean and sample standard deviation per `(region, hour, weekend, month)`
- Flag `|z| > 3`; `|z| > 4` is **CRITICAL**, otherwise **WARNING**

```python
group_keys = ["region", "hour", "weekend", "month"]
stats = featured.groupBy(*group_keys).agg(
    F.avg("mw").alias("expected_mw"),
    F.stddev_samp("mw").alias("baseline_stddev"),
)
scored = featured.join(F.broadcast(stats), group_keys, "inner")
```

### 5. Rolling-Window Detection (comparison)
- Per-region window over the preceding 168 hours, excluding the current reading
- Same thresholds and severity bands

### 6. Storage and Alerting
- JDBC write to `anomalies_stage` through the Session Pooler, then merged into `anomalies` with `ON CONFLICT DO NOTHING`
- A webhook triggers the Edge Function, which emails CRITICAL rows through Resend

## 📊 Key Results

| Measure | Value |
|---|---|
| Rows ingested | 1,090,167 |
| Non-positive MW rows removed | 1 |
| Duplicate rows removed | 40 |
| Clean rows retained | 1,090,126 |
| Contextual z-score anomalies | 6,024 |
| Rolling-window anomalies | 1,418 |
| Shared region–timestamp keys | 125 |
| Jaccard overlap | 0.017 |
| New rows inserted into Supabase | 5,166 |

The low overlap shows the detectors use different baselines and pick different observations. With no labelled data, neither is called more accurate.

**Event-date screening** (temporal overlap only, not causation):

| Event | Flagged rows | Series |
|---|---|---|
| Northeast blackout (Aug 2003) | 0 | 0 |
| June 2012 derecho | 70 | 6 |
| Hurricane Sandy (Oct 2012) | 32 | 2 |
| January 2014 polar vortex | 52 | 6 |

## 🖥️ Dashboard

- Filters for region, severity and date range; refresh button and 30-second auto-refresh
- Summary cards: anomaly records, critical anomalies, warnings, critical alerts marked sent
- Charts: anomalies per region, severity split, region-by-hour heatmap, MW time series with anomaly overlay, and an events/email-status chart
- Latest-anomalies table with a manual email control that asks for confirmation before sending

## 🛠️ Technologies Used

- **Processing:** Python, Apache PySpark
- **Database:** Supabase Postgres (JDBC, Session Pooler)
- **Alerting:** Database Webhooks, Edge Functions (TypeScript/Deno), Resend
- **Dashboard:** Streamlit
- **Environment:** Local machine or Google Colab

## 💡 Key Insights

- Contextual baselines and rolling baselines flag very different readings
- Unique keys at the database boundary make reruns safe
- `alerted = true` means Resend accepted the email, not that it reached an inbox; check the inbox or Resend logs
- A synthetic `DEMO` record was used only to test the alert path and is not part of the PJM analysis

## ⚠️ Limitations

- Unsupervised, with no ground-truth labels
- Baselines can be skewed by anomalies in the history; sparse groups and zero standard deviations can't be scored
- Daylight-saving changes may create ambiguous or duplicate timestamps
- Local Spark session, not a multi-node cluster
- The dashboard is a demo, not a production control system

## 🔮 Future Work

- Robust baselines (median/MAD) or winsorized estimates
- Weather, holiday and system-event features
- Operator feedback to measure precision, recall and false alarms
- Alert deduplication, rate limits and escalation
- Supabase Realtime for the dashboard
- A managed or multi-node Spark cluster
- Authenticated dashboard users

## 🔒 Security Notes

- Keep passwords, privileged keys and API secrets out of source control
- The dashboard uses only the project URL and a publishable/anon key under Row Level Security

## 🙏 Acknowledgments

- Dataset: Robikscube, Hourly Energy Consumption (Kaggle), based on PJM data
- Docs: Apache Spark, Supabase, Resend, Streamlit

## 📞 Contact

**Kancharla Vaishnavi Reddy**
GitHub: [KancharlaVaishnaviReddy](https://github.com/KancharlaVaishnaviReddy)

⭐ If you find this project useful, please star the repository!
