"""Shared configuration and environment-variable loading."""

from dataclasses import dataclass
import os
from pathlib import Path

from dotenv import load_dotenv


ROOT_DIR = Path(__file__).resolve().parents[1]
load_dotenv(ROOT_DIR / ".env")


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    artifacts_dir: Path
    jdbc_host: str
    jdbc_port: int
    jdbc_database: str
    jdbc_user: str
    jdbc_password: str
    jdbc_sslmode: str
    supabase_url: str
    supabase_anon_key: str

    @property
    def jdbc_url(self) -> str:
        return (
            f"jdbc:postgresql://{self.jdbc_host}:{self.jdbc_port}/"
            f"{self.jdbc_database}?sslmode={self.jdbc_sslmode}"
        )

    @property
    def jdbc_properties(self) -> dict[str, str]:
        return {
            "user": self.jdbc_user,
            "password": self.jdbc_password,
            "driver": "org.postgresql.Driver",
        }


def get_settings(require_database: bool = True) -> Settings:
    """Load settings and fail early with a helpful message if values are missing."""
    data_dir = Path(os.getenv("DATA_DIR", "data"))
    artifacts_dir = Path(os.getenv("ARTIFACTS_DIR", "artifacts"))

    if not data_dir.is_absolute():
        data_dir = ROOT_DIR / data_dir
    if not artifacts_dir.is_absolute():
        artifacts_dir = ROOT_DIR / artifacts_dir

    db_values = {
        "SUPABASE_DB_HOST": os.getenv("SUPABASE_DB_HOST"),
        "SUPABASE_DB_USER": os.getenv("SUPABASE_DB_USER"),
        "SUPABASE_DB_PASSWORD": os.getenv("SUPABASE_DB_PASSWORD"),
    }
    if require_database:
        missing = [name for name, value in db_values.items() if not value]
        if missing:
            raise ValueError(
                "Missing database environment variables: "
                + ", ".join(missing)
                + ". Copy .env.example to .env and fill them in."
            )

    return Settings(
        data_dir=data_dir,
        artifacts_dir=artifacts_dir,
        jdbc_host=db_values["SUPABASE_DB_HOST"] or "",
        jdbc_port=int(os.getenv("SUPABASE_DB_PORT", "5432")),
        jdbc_database=os.getenv("SUPABASE_DB_NAME", "postgres"),
        jdbc_user=db_values["SUPABASE_DB_USER"] or "",
        jdbc_password=db_values["SUPABASE_DB_PASSWORD"] or "",
        jdbc_sslmode=os.getenv("SUPABASE_DB_SSLMODE", "require"),
        supabase_url=os.getenv("SUPABASE_URL", ""),
        supabase_anon_key=os.getenv("SUPABASE_ANON_KEY", ""),
    )
