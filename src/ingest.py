"""Read the individual regional PJM CSV files and union them."""

from pathlib import Path

from pyspark.sql import DataFrame, SparkSession
from pyspark.sql import functions as F


def find_region_files(data_dir: Path, regions: list[str] | None = None) -> list[tuple[str, Path]]:
    """Return (region, path) pairs, excluding the combined estimate file."""
    files = []
    requested = {r.strip().upper() for r in regions} if regions else None

    for path in sorted(data_dir.glob("*.csv")):
        if path.name.lower() == "pjm_hourly_est.csv":
            continue
        region = path.stem.split("_")[0].upper()
        if requested and region not in requested:
            continue
        files.append((region, path))

    if not files:
        raise FileNotFoundError(
            f"No regional CSV files found in {data_dir}. "
            "Extract the Kaggle CSVs into the data/ directory."
        )
    return files


def ingest_regions(
    spark: SparkSession,
    data_dir: Path,
    regions: list[str] | None = None,
) -> DataFrame:
    """Read every matching file, normalize columns, and union the frames."""
    frames = []

    for region, path in find_region_files(data_dir, regions):
        raw = (
            spark.read
            .option("header", True)
            .option("inferSchema", True)
            .option("mode", "PERMISSIVE")
            .csv(str(path))
        )

        # Dataset files have a Datetime column and one region-specific MW column.
        datetime_col = next((c for c in raw.columns if c.lower() == "datetime"), None)
        mw_col = next(
            (c for c in raw.columns if c.lower() not in {"datetime", "_corrupt_record"}),
            None,
        )
        if not datetime_col or not mw_col:
            raise ValueError(f"Unexpected columns in {path.name}: {raw.columns}")

        frames.append(
            raw.select(
                F.col(datetime_col).alias("raw_ts"),
                F.col(mw_col).alias("raw_mw"),
            ).withColumn("region", F.lit(region))
        )
        print(f"[ingest] Loaded {path.name} for region {region}")

    result = frames[0]
    for frame in frames[1:]:
        result = result.unionByName(frame)

    print(f"[ingest] Rows read: {result.count():,}")
    return result
