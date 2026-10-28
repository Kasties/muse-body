"""Settings read from the environment (and an optional .env file)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def load_dotenv(path: Path = Path(".env")) -> None:
    """Minimal .env loader: KEY=VALUE lines, existing env vars win."""
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


@dataclass(frozen=True)
class Settings:
    api_key: str
    base_url: str = "https://api.meta.ai/v1"
    model: str = "muse-spark-1.3"
    sam_model: str = "sam-3.1"
    osc_host: str = "127.0.0.1"
    osc_port: int = 9000
    # VRChat desktop camera: vertical field of view in degrees.
    fov_v_deg: float = 70.0

    @classmethod
    def from_env(cls) -> "Settings":
        load_dotenv()
        key = os.environ.get("MODEL_API_KEY", "")
        if not key:
            raise SystemExit("MODEL_API_KEY is not set (see .env.example)")
        return cls(
            api_key=key,
            base_url=os.environ.get("MUSE_BASE_URL", cls.base_url),
            model=os.environ.get("MUSE_MODEL", cls.model),
            sam_model=os.environ.get("MUSE_SAM_MODEL", cls.sam_model),
            osc_host=os.environ.get("VRCHAT_OSC_HOST", cls.osc_host),
            osc_port=int(os.environ.get("VRCHAT_OSC_PORT", cls.osc_port)),
        )
