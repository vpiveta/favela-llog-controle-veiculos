from __future__ import annotations

import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = PROJECT_ROOT / ".env"


def load_env_file() -> None:
    """Carrega .env sem depender da pasta atual do terminal."""
    try:
        from dotenv import load_dotenv
        load_dotenv(ENV_FILE, override=True)
    except Exception:
        pass


def set_project_directory() -> None:
    os.chdir(PROJECT_ROOT)


def normalize_database_url(value: str) -> str:
    value = (value or "").strip().strip('"').strip("'")
    if value.startswith("postgres://"):
        value = "postgresql://" + value[len("postgres://"):]
    return value


def write_env(updates: dict[str, str]) -> None:
    current: dict[str, str] = {}
    if ENV_FILE.exists():
        for raw in ENV_FILE.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, val = line.split("=", 1)
            current[key.strip()] = val
    current.update(updates)
    preferred = ["SECRET_KEY", "DATABASE_URL", "APP_URL"]
    ordered = preferred + sorted(k for k in current if k not in preferred)
    text = "\n".join(f"{key}={current[key]}" for key in ordered if key in current) + "\n"
    ENV_FILE.write_text(text, encoding="utf-8")
