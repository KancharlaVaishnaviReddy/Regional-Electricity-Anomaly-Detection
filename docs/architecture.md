# Architecture

```mermaid
flowchart LR
    A[Kaggle regional CSVs] --> B[PySpark ingestion]
    B --> C[Clean, deduplicate, feature engineer]
    C --> D[Contextual z-score detector]
    C --> E[168-hour rolling detector]
    D --> F[JDBC to Supabase staging]
    F --> G[Idempotent insert into anomalies]
    G --> H[Supabase INSERT Database Webhook]
    H --> I[Supabase Edge Function: alert]
    I --> J[Resend email]
    I -. optional .-> K[Twilio SMS]
    G --> L[Supabase REST / Realtime]
    L --> M[Streamlit dashboard]
    A --> M
