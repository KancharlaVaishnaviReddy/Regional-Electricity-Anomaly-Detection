import os
import psycopg2
from dotenv import load_dotenv

load_dotenv()

conn = psycopg2.connect(
    host=os.environ["SUPABASE_DB_HOST"],
    port=int(os.getenv("SUPABASE_DB_PORT", "5432")),
    dbname=os.getenv("SUPABASE_DB_NAME", "postgres"),
    user=os.environ["SUPABASE_DB_USER"],
    password=os.environ["SUPABASE_DB_PASSWORD"],
    sslmode=os.getenv("SUPABASE_DB_SSLMODE", "require"),
)

with conn.cursor() as cur:
    cur.execute("select current_database(), current_user")
    print("Database connection successful:", cur.fetchone())

conn.close()
