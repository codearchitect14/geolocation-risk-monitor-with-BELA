"""Runtime settings read from the environment."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_DATABASE_URL = "postgresql+psycopg://meridian:meridian@localhost:5433/meridian"


def _load_env_file() -> None:
    """Read KEY=VALUE pairs from the repository .env without overriding the environment."""
    try:
        lines = (REPO_ROOT / ".env").read_text(encoding="utf-8").splitlines()
    except OSError:
        return
    for line in lines:
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_env_file()


@dataclass(frozen=True)
class Settings:
    database_url: str
    data_dir: Path
    embedding_model: str
    embedding_dim: int

    @property
    def psycopg_dsn(self) -> str:
        """Connection string for plain psycopg (no SQLAlchemy driver suffix)."""
        return self.database_url.replace("postgresql+psycopg://", "postgresql://", 1)


def get_settings() -> Settings:
    override = os.environ.get("MS_DATA_DIR", "").strip()
    return Settings(
        database_url=os.environ.get("DATABASE_URL", "").strip() or DEFAULT_DATABASE_URL,
        data_dir=Path(override).expanduser() if override else REPO_ROOT / "data",
        embedding_model=os.environ.get("EMBEDDING_MODEL", "BAAI/bge-m3"),
        embedding_dim=1024,
    )
