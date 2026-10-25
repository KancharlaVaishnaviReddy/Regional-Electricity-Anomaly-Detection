"""Calendar features used by the contextual detector."""

from pyspark.sql import DataFrame
from pyspark.sql import functions as F


def add_calendar_features(df: DataFrame) -> DataFrame:
    # Spark dayofweek: Sunday=1, Saturday=7.
    return (
        df.withColumn("hour", F.hour("ts"))
        .withColumn("day_of_week", F.dayofweek("ts"))
        .withColumn("weekend", F.dayofweek("ts").isin([1, 7]))
        .withColumn("month", F.month("ts"))
    )
