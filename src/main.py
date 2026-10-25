"""Run the complete PySpark anomaly-detection pipeline."""

import argparse
import os
import sys
from pathlib import Path

from pyspark.sql import SparkSession

from clean import clean_data
from config import get_settings
from detect_rolling import compare_detectors, detect_rolling
from detect_zscore import detect_zscore
from features import add_calendar_features
from ingest import ingest_regions
from write_supabase import write_anomalies


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--regions",
        help="Comma-separated region list for a quick test, e.g. AEP,COMED",
    )
    parser.add_argument(
        "--no-write",
        action="store_true",
        help="Run detection and save local artifacts, but do not connect to Supabase.",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    regions = [r.strip().upper() for r in args.regions.split(",")] if args.regions else None
    settings = get_settings(require_database=not args.no_write)
    settings.artifacts_dir.mkdir(parents=True, exist_ok=True)

    # Spark downloads the PostgreSQL JDBC driver if it is not already installed.
    spark = (
        SparkSession.builder.appName("RegionalElectricityAnomalyDetection")
        .config("spark.jars.packages", "org.postgresql:postgresql:42.7.3")
        .config("spark.sql.session.timeZone", "UTC")
        .getOrCreate()
    )
    spark.sparkContext.setLogLevel("WARN")

    try:
        raw = ingest_regions(spark, settings.data_dir, regions)
        clean = clean_data(raw).cache()
        print(f"[main] Cleaned rows: {clean.count():,}")

        featured = add_calendar_features(clean).cache()
        zscore = detect_zscore(featured).cache()
        rolling = detect_rolling(clean).cache()

        z_count = zscore.count()
        print(f"[main] Z-score anomaly rows: {z_count:,}")
        print(f"[main] Rolling anomaly rows: {rolling.count():,}")
        compare_detectors(zscore, rolling)

        # Persist data used by the report notebook and local dashboard.
        clean.write.mode("overwrite").parquet(
            str(settings.artifacts_dir / "cleaned")
        )
        zscore.write.mode("overwrite").parquet(
            str(settings.artifacts_dir / "anomalies_zscore")
        )
        rolling.write.mode("overwrite").parquet(
            str(settings.artifacts_dir / "anomalies_rolling")
        )
        print(f"[main] Local parquet artifacts saved to {settings.artifacts_dir}")

        if not args.no_write:
            write_anomalies(zscore, settings)
        else:
            print("[main] --no-write supplied; skipped Supabase storage.")

        clean.unpersist()
        featured.unpersist()
        zscore.unpersist()
        rolling.unpersist()
    finally:
        spark.stop()


if __name__ == "__main__":
    main()
