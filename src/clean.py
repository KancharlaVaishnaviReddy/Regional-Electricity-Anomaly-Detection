"""Timestamp/value validation and duplicate removal."""

from pyspark.sql import DataFrame
from pyspark.sql import functions as F


def clean_data(raw: DataFrame) -> DataFrame:
    before = raw.count()
    parsed = raw.select(
        F.to_timestamp(F.col("raw_ts")).alias("ts"),
        F.col("raw_mw").cast("double").alias("mw"),
        F.upper(F.trim(F.col("region"))).alias("region"),
    )
    parsed_count = parsed.count()
    print(f"[clean] Invalid/unparseable timestamp or MW rows removed: {before - parsed_count:,}")

    non_null = parsed.dropna(subset=["ts", "mw", "region"])
    non_null_count = non_null.count()
    print(f"[clean] Null rows removed: {parsed_count - non_null_count:,}")

    positive = non_null.filter(F.col("mw") > 0)
    positive_count = positive.count()
    print(f"[clean] Non-positive MW rows removed: {non_null_count - positive_count:,}")

    deduplicated = positive.dropDuplicates(["region", "ts"])
    final_count = deduplicated.count()
    print(f"[clean] Duplicate (region, ts) rows removed: {positive_count - final_count:,}")
    print(f"[clean] Clean rows: {final_count:,}")

    return deduplicated.select("region", "ts", "mw")
