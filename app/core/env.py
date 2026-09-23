"""Small local .env loader for runtime configuration.

This intentionally avoids adding a dependency. Values already present in the environment
win over local file values.
"""

from __future__ import annotations

import os
from pathlib import Path


def load_env_file(project_root: Path) -> None:
    env_path = project_root / ".env"
    if not env_path.is_file():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value
