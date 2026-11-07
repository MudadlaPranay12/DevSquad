"""
DEV-SQUAD — runtime configuration.

All settings come from environment variables with safe local defaults.
No credentials are hardcoded. The pairing token is generated once and stored
in bridge/.devsquad_token (gitignored), or supplied through DEV_SQUAD_TOKEN.
"""

from __future__ import annotations

import os
import secrets
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
BRIDGE_DIR = PROJECT_ROOT / "bridge"
BUNDLES_DIR = PROJECT_ROOT / "bundles"
DATA_DIR = BRIDGE_DIR / "data"
TOKEN_PATH = BRIDGE_DIR / ".devsquad_token"

DEFAULT_MODEL = "opencode/deepseek-v4.1-flash-free"
DEFAULT_TRANSPORT = "local"


def get_db_path() -> Path:
    """Return the SQLite path, allowing tests and deployments to override it."""
    raw = os.environ.get("DEV_SQUAD_DB")
    return Path(raw) if raw else DATA_DIR / "devsquad.db"


def ensure_pairing_token() -> str:
    """Return the pairing token, generating a local one on first use.

    The token is never written to source control. It is intended to be copied
    into the DevTools extension settings by the developer.
    """
    env_token = os.environ.get("DEV_SQUAD_TOKEN")
    if env_token:
        return env_token

    if TOKEN_PATH.exists():
        token = TOKEN_PATH.read_text(encoding="utf-8").strip()
        if token:
            return token

    token = secrets.token_urlsafe(32)
    TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    TOKEN_PATH.write_text(token + "\n", encoding="utf-8")
    try:
        TOKEN_PATH.chmod(0o600)
    except OSError:
        pass
    return token


def require_pairing_token() -> bool:
    """Whether mutating API calls require X-DevSquad-Token."""
    return os.environ.get("DEV_SQUAD_REQUIRE_TOKEN", "1").lower() not in {"0", "false", "no"}


def agent_model() -> str:
    return os.environ.get("DEV_SQUAD_MODEL", DEFAULT_MODEL)


def transport_mode() -> str:
    return os.environ.get("DEV_SQUAD_TRANSPORT", DEFAULT_TRANSPORT).lower()


def opencode_command() -> str:
    return os.environ.get("DEV_SQUAD_OPENCODE", "opencode")


def agent_timeout_seconds() -> int:
    try:
        return int(os.environ.get("DEV_SQUAD_AGENT_TIMEOUT", "180"))
    except ValueError:
        return 180


def investigation_timeout_seconds() -> int:
    try:
        return int(os.environ.get("DEV_SQUAD_INVESTIGATION_TIMEOUT", "600"))
    except ValueError:
        return 600


def max_evidence_items() -> int:
    try:
        return int(os.environ.get("DEV_SQUAD_MAX_EVIDENCE", "500"))
    except ValueError:
        return 500


def max_bundle_bytes() -> int:
    try:
        return int(os.environ.get("DEV_SQUAD_MAX_BUNDLE_BYTES", str(4 * 1024 * 1024)))
    except ValueError:
        return 4 * 1024 * 1024


def allowed_hosts() -> set[str]:
    extra = os.environ.get("DEV_SQUAD_ALLOWED_HOSTS", "")
    hosts = {
        "127.0.0.1",
        "localhost",
        "127.0.0.1:8000",
        "localhost:8000",
        "testserver",
    }
    hosts.update(h.strip() for h in extra.split(",") if h.strip())
    return hosts


def allowed_origins() -> list[str]:
    extra = os.environ.get("DEV_SQUAD_ALLOWED_ORIGINS", "")
    origins = ["http://127.0.0.1:8000", "http://localhost:8000"]
    origins.extend(o.strip() for o in extra.split(",") if o.strip())
    return origins
