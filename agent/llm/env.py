"""API keys come ONLY from environment variables or a local `.env` (gitignored). Keys are never
logged, never put into prompts, never written to disk by this project."""
from __future__ import annotations

import os
from pathlib import Path

from agent.config import ROOT

_LOADED = False


def load_dotenv(path: Path | None = None) -> None:
    """Minimal .env reader (KEY=VALUE lines). Existing environment variables win."""
    global _LOADED
    p = path or ROOT / ".env"
    if _LOADED and path is None:
        return
    _LOADED = True
    if not p.exists():
        return
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k, v = k.strip(), v.strip().strip('"').strip("'")
        if k and v and k not in os.environ:
            os.environ[k] = v


def get_key(name: str) -> str | None:
    load_dotenv()
    v = os.environ.get(name)
    return v or None


def redact(text: str) -> str:
    """Remove any configured key value from a string (defence in depth for logs)."""
    for name in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY"):
        v = os.environ.get(name)
        if v and v in text:
            text = text.replace(v, "***REDACTED***")
    return text
