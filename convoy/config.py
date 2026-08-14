"""Minimal .env loader.

Python does not read .env files on its own, and this project has no third-party
dependencies -- so python-dotenv is not an option. This is the ~20 lines of it
that matter.

Real environment variables always win. That way `OPENROUTER_API_KEY=... python3
run_phase2.py` overrides the file without editing it, which is what you want
when switching between keys.
"""

from __future__ import annotations

import os
from pathlib import Path

# Repo root: this file is convoy/config.py, so up two levels.
DEFAULT_ENV_PATH = Path(__file__).resolve().parent.parent / ".env"


def load_env(path: Path | str | None = None, *, override: bool = False) -> dict[str, str]:
    """Read KEY=value lines into os.environ. Returns what was loaded.

    Silently does nothing if the file is absent -- exporting the variable
    directly is an equally valid setup, so a missing .env is not an error.
    """
    env_path = Path(path) if path else DEFAULT_ENV_PATH
    loaded: dict[str, str] = {}
    if not env_path.is_file():
        return loaded

    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):          # tolerate shell-style files
            line = line[len("export "):].lstrip()
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip()
        # Strip one matched pair of surrounding quotes.
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        if not key:
            continue
        if override or key not in os.environ:
            os.environ[key] = value
            loaded[key] = value
    return loaded
