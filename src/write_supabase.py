"""Write through JDBC to staging, then insert idempotently into anomalies."""

import os
import uuid

import psycopg2
from pyspark.sql import DataFrame
from pyspark.sql import functions as F

from config import Settings


def write_anomalies(anomalies: DataFrame, settings: Settings) -> int:
    """Persist anomaly rows and return the number newly inserted."""
    run_id = str(uuid.uuid4())
    staged = anomalies.withColumn("run_id", F.lit(run_id))

    # Coalesce avoids opening an unnecessarily large number of pooler connections.
    # JDBC batchsize reduces round trips; tune partitions for the available pool.
    (
        staged.coalesce(4)
        .write.format("jdbc")
        .option("url", settings.jdbc_url)
        .option("dbtable", "public.anomalies_stage")
        .option("user", settings.jdbc_user)
        .option("password", settings.jdbc_password)
        .option("driver", "org.postgresql.Driver")
        .option("batchsize", "1000")
        .option("numPartitions", "4")
        .mode("append")
        .save()
    )

    conn = psycopg2.connect(
        host=settings.jdbc_host,
        port=settings.jdbc_port,
        dbname=settings.jdbc_database,
        user=settings.jdbc_user,
        password=settings.jdbc_password,
        sslmode=settings.jdbc_sslmode,
    )
    inserted = 0
    try:
        with conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO public.anomalies
                        (region, ts, mw, expected_mw, z_score, severity)
                    SELECT region, ts, mw, expected_mw, z_score, severity
                    FROM public.anomalies_stage
                    WHERE run_id = %s
                    ON CONFLICT (region, ts) DO NOTHING
                    """,
                    (run_id,),
                )
                inserted = cursor.rowcount
                cursor.execute(
                    "DELETE FROM public.anomalies_stage WHERE run_id = %s",
                    (run_id,),
                )
    finally:
        conn.close()

    print(f"[storage] Newly inserted rows: {inserted:,} (run_id={run_id})")
    return inserted
