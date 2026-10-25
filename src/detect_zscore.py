"""Contextual z-score detector: region/hour/weekend/month baseline."""

from pyspark.sql import DataFrame
from pyspark.sql import functions as F


def detect_zscore(df: DataFrame) -> DataFrame:
    keys = ["region", "hour", "weekend", "month"]
    stats = (
        df.groupBy(*keys)
        .agg(
            F.avg("mw").alias("expected_mw"),
            F.stddev_samp("mw").alias("baseline_stddev"),
        )
    )

    # The grouped statistics are small relative to the hourly observations.
    scored = (
        df.join(F.broadcast(stats), on=keys, how="inner")
        .withColumn(
            "z_score",
            F.when(
                F.col("baseline_stddev").isNotNull()
                & (F.col("baseline_stddev") > 0),
                (F.col("mw") - F.col("expected_mw")) / F.col("baseline_stddev"),
            ),
        )
    )

    return (
        scored.filter(F.col("z_score").isNotNull() & (F.abs("z_score") > 3))
        .withColumn(
            "severity",
            F.when(F.abs("z_score") > 4, F.lit("CRITICAL"))
            .otherwise(F.lit("WARNING")),
        )
        .select("region", "ts", "mw", "expected_mw", "z_score", "severity")
    )
