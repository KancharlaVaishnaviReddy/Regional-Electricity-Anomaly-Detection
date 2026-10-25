# ⚡ Anomaly Detection in Regional Electricity Consumption

An end-to-end pipeline for detecting unusual hourly electricity consumption across PJM regions, storing flagged anomalies in Supabase, showing them in an interactive Streamlit dashboard, and sending email alerts for critical events.

> Anomaly flags are statistical indicators for review. They do not, by themselves, prove that an outage occurred or identify its cause.

## 📊 Project Overview

This project analyzes hourly regional electricity-consumption data, flags readings that deviate from expected consumption, and presents the results in a live dashboard. Critical anomalies can trigger an email alert through a Supabase Edge Function and Resend.

**Pipeline Flow:**

```
Hourly MW Data → Expected-Consumption Model → Z-Score Anomaly Detection →
Severity Classification (WARNING / CRITICAL) → Supabase Storage →
Streamlit Dashboard → Email Alerts (Edge Function + Resend)
```

## 🎯 Key Features

- **Anomaly Detection:** Compares observed MW against expected MW and scores each reading with a Z-score.
- **Severity Levels:** Flags are classified as `WARNING` or `CRITICAL`.
- **Cloud Storage:** Anomaly records are stored in a Supabase table and summarized in an `anomaly_summary` view.
- **Interactive Dashboard (Streamlit):**
  - KPI cards for total anomalies, critical anomalies, warnings, and alerts marked sent
  - Anomalies per region and severity split by region
  - MW time series with observed consumption and flagged anomaly readings
  - Anomaly pattern by hour of day (heatmap)
  - Filters for region, severity, and date range
  - Latest anomalies table with observed MW, expected MW, Z-score, severity, and email status
  - Auto-refresh on a configurable interval
- **Email Alerts:** Supabase Edge Function and Resend, with a manual resend option for selected critical anomalies.

## 📈 Dataset

**Source:** PJM hourly energy consumption data, available on Kaggle (verify the exact dataset name and license before publishing).

**Dataset Stats:** *(fill in from your data)*

- Hourly consumption readings in MW, one CSV per region
- Regions such as `AEP`, `DOM`, and `PJME`
- Number of regions: `[N]`
- Date range: `[start] – [end]`
- Total hourly records: `[N]`
- Anomalies flagged: `[N]` (`[X]%` of records)

Each CSV needs a timestamp column named `datetime`, `timestamp`, `ts`, or `date`, and one numeric MW column.

## 🚀 Quick Start

### Prerequisites

- Python 3.10+
- A Supabase project
- A Resend account (for email alerts)
- Node.js and the Supabase CLI (to deploy the Edge Function)

### Installation

1. **Clone the repository**

   ```bash
   git clone <YOUR_GITHUB_REPOSITORY_URL>
   cd <YOUR_REPOSITORY_FOLDER>
   ```

2. **Create and activate a virtual environment**

   ```bash
   # Windows PowerShell
   python -m venv .venv
   .venv\Scripts\Activate.ps1

   # macOS / Linux
   python3 -m venv .venv
   source .venv/bin/activate
   ```

3. **Install dependencies**

   ```bash
   pip install -r requirements.txt
   ```

4. **Add the data**

   - Place the regional CSV files in the `data/` folder, or set `DATA_DIR` in `.env`.
   - Name each file with the region as the prefix, for example `AEP_hourly.csv`.

5. **Configure the environment** (see [Configuration](#️-configuration))

6. **Run the dashboard**

   ```bash
   streamlit run dashboard/app.py
   ```

   Then open `http://localhost:8501`.

## 📋 Project Structure

The structure below is an example. Keep your actual folder and file names if they differ.

```
electricity-anomaly/
├── README.md                          # This file
├── data/                              # Regional CSV files (gitignored)
├── artifacts/                         # Generated charts and tables
├── dashboard/
│   └── app.py                         # Streamlit dashboard
├── notebooks/
│   └── electricity_anomaly.ipynb      # Analysis / detection notebook
├── supabase/
│   └── functions/
│       └── alert/
│           └── index.ts               # Edge Function for email alerts
├── .env.example                       # Environment template (no real secrets)
├── .gitignore
└── requirements.txt                   # Python dependencies
```

## 🔬 Pipeline Stages

### 1. Data Loading & Preparation
- Load hourly MW readings for each region
- Parse timestamps and convert MW to numeric values
- Drop rows with missing timestamps or values

### 2. Expected-Consumption Modeling
- Estimate expected MW for each timestamp *(describe your method here, for example a rolling or hour-of-day baseline)*
- Compare observed MW with expected MW

### 3. Anomaly Detection
- Compute a Z-score for each reading
- Flag readings whose Z-score exceeds the configured thresholds *(add your threshold values)*

### 4. Severity Classification
- `WARNING`: moderate deviation from expected consumption
- `CRITICAL`: large deviation, eligible for email alerts

### 5. Storage in Supabase
- Insert flagged records into the `anomalies` table
- Fields include `region`, `ts`, `mw`, `expected_mw`, `z_score`, `severity`, `alerted`, and `created_at`
- Aggregate counts are exposed through `anomaly_summary`

### 6. Dashboard & Alerts
- Streamlit reads from Supabase for anomaly records and from local CSVs for the MW history
- A database webhook or the manual action calls the `alert` Edge Function, which sends the email through Resend and updates the `alerted` flag

## 🖥️ Dashboard Walkthrough

| Section | What it shows |
|---|---|
| KPI cards | Anomaly records, critical anomalies, warnings, critical alerts marked sent |
| Anomalies per Region | Bar chart of anomaly counts by region |
| Severity Split by Region | Stacked bars of `WARNING` vs `CRITICAL` per region |
| MW Time Series | Light blue observed MW line with a dark blue anomaly MW line, weekly date labels, no axis titles |
| Anomaly Pattern by Hour | Heatmap of anomaly counts by region and hour of day |
| Latest Anomalies | Table of recent flags, plus a manual email control for critical anomalies |

## 🛠️ Configuration

Create a `.env` file in the repository root. **Do not commit it.**

```dotenv
# Dashboard access to Supabase
SUPABASE_URL=https://YOUR_PROJECT_REF.supabase.co
SUPABASE_ANON_KEY=YOUR_SUPABASE_PUBLISHABLE_OR_ANON_KEY

# Optional dashboard settings
DATA_DIR=data
DASHBOARD_REFRESH_SECONDS=30

# Required only for the manual email action
MANUAL_ALERT_SECRET=YOUR_SHARED_RANDOM_SECRET
```

Use only the Supabase **publishable/anon key** in the dashboard. Never put a service-role key in Streamlit code or a shared notebook.

### Edge Function secrets (set in Supabase, not in Git)

```text
RESEND_API_KEY
ALERT_FROM_EMAIL
ALERT_TO_EMAIL
WEBHOOK_SECRET
MANUAL_ALERT_SECRET
```

`MANUAL_ALERT_SECRET` must match in your local `.env` and in Supabase.

## 📧 Email Alerts

1. Confirm the sender and recipient settings.
2. Confirm that the function secrets are configured.
3. Select the intended critical anomaly in the dashboard.
4. Tick the confirmation box and click **Send email**.
5. Check the recipient inbox and the Resend logs.

The dashboard's "Email marked sent" status reflects the `alerted` field in the database. It does not independently guarantee inbox delivery.

## 🧰 Technologies Used

- **Data Processing:** NumPy, Pandas
- **Dashboard:** Streamlit, streamlit-autorefresh
- **Visualization:** Plotly
- **Database:** Supabase (PostgreSQL)
- **Alerts:** Supabase Edge Functions, Resend
- **Environment:** Python, python-dotenv, Requests, Jupyter / Google Colab

## 📥 Dependencies

```
streamlit>=1.39.0
pandas>=1.3.0
numpy>=1.21.0
plotly>=5.0.0
python-dotenv>=1.0.0
streamlit-autorefresh>=1.0.0
supabase>=2.0.0
requests>=2.28.0
```

Streamlit 1.39 or newer is needed for the borderless MW time series chart.

## 📊 Key Results

*(fill in from your own runs)*

| Metric | Value |
|---|---|
| Regions analyzed | `[N]` |
| Anomalies flagged | `[N]` |
| Critical anomalies | `[N]` |
| Warnings | `[N]` |
| Critical alerts emailed | `[N]` |

## 💡 Key Insights

*(replace with what your analysis shows)*

- Consumption follows a strong daily cycle and a seasonal pattern, with higher summer peaks.
- Anomalies are easiest to interpret when compared against expected MW, not raw MW alone.
- The hour-of-day heatmap shows when flags cluster for each region.

## ⚙️ Customization

**Refresh interval:**

```dotenv
DASHBOARD_REFRESH_SECONDS=60
```

**Maximum records loaded by the dashboard:**

```python
MAX_RECORDS = 5000
```

**MW chart colours:**

```python
MW_OBSERVED = "#83C9FF"   # observed line
MW_ANOMALY = "#0068C9"    # anomaly line
```

## 🔧 Troubleshooting

| Problem | What to check |
|---|---|
| Missing Supabase settings | `.env` is in the repository root and has `SUPABASE_URL` and `SUPABASE_ANON_KEY`. Restart Streamlit after editing. |
| No regional CSV found | `DATA_DIR` points to the right folder and the filename starts with the region name. |
| CSV columns not recognized | The file has a `datetime`, `timestamp`, `ts`, or `date` column and a separate numeric MW column. |
| Email action fails | The Edge Function is deployed, the URL is correct, and `MANUAL_ALERT_SECRET` matches in `.env` and Supabase. Check function and Resend logs. |
| Email not shown as sent | The function updates the `alerted` field. Refresh the dashboard and check inbox delivery separately. |
| MW chart still has a border | Run `pip install -U streamlit` (needs 1.39+). |

## 🔒 Security

- Never commit `.env`, API keys, database passwords, or webhook secrets.
- Do not use a Supabase service-role key in the dashboard.
- Rotate any credential that was accidentally exposed.
- Keep private or licensed datasets out of public repositories.

## 🤝 Contributing

Feel free to fork this project and submit pull requests. Please keep credentials and private data out of commits and test the dashboard locally first.

## 📝 License

Add your chosen license here (for example MIT) and include a `LICENSE` file.

## 🙏 Acknowledgments

- Dataset: PJM hourly energy consumption data (Kaggle)
- Built with Streamlit, Supabase, Plotly, and Resend

## 📞 Contact

- GitHub:  KancharlaVaishnaviReddy
- Repository: https://github.com/KancharlaVaishnaviReddy/Regional-Electricity-Anomaly-Detection

⭐ If you find this project useful, please star the repository!
