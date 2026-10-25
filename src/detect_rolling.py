"""Rolling detector based on the preceding 168 hours for each region."""

from pyspark.sql import DataFrame, Window
from pyspark.sql import functions as F


def detect_rolling(df: DataFrame) -> DataFrame:
    # Use epoch seconds so gaps in the data do not turn a 168-row window
    # into a window longer or shorter than 168 hours.
    seconds = F.col("ts").cast("long")
    window = (
        Window.partitionBy("region")
        .orderBy(seconds)
        .rangeBetween(-168 * 60 * 60, -1)
    )

    scored = (
        df.withColumn("_epoch", seconds)
        .withColumn("_expected", F.avg("mw").over(window))
        .withColumn("_stddev", F.stddev_samp("mw").over(window))
        .withColumn(
            "_z",
            F.when(
                F.col("_stddev").isNotNull() & (F.col("_stddev") > 0),
                (F.col("mw") - F.col("_expected")) / F.col("_stddev"),
            ),
        )
    )

    return (
        scored.filter(F.col("_z").isNotNull() & (F.abs("_z") > 3))
        .withColumn(
            "severity",
            F.when(F.abs("_z") > 4, F.lit("CRITICAL"))
            .otherwise(F.lit("WARNING")),
        )
        .select(
            "region",
            "ts",
            F.col("mw"),
            F.col("_expected").alias("expected_mw"),
            F.col("_z").alias("z_score"),
            "severity",
        )
    )


def compare_detectors(zscore: DataFrame, rolling: DataFrame) -> None:
    z_count = zscore.count()
    r_count = rolling.count()
    overlap = (
        zscore.select("region", "ts")
        .join(rolling.select("region", "ts"), ["region", "ts"], "inner")
        .count()
    )
    print(f"[compare] Contextual z-score anomalies: {z_count:,}")
    print(f"[compare] Rolling-window anomalies: {r_count:,}")
    print(f"[compare] Overlap (same region and timestamp): {overlap:,}")
