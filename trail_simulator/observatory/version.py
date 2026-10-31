"""The backend's version string: package version plus the git short SHA."""
from __future__ import annotations

import subprocess
from functools import lru_cache

from .. import __version__
from ..config import PROJECT_ROOT


@lru_cache(maxsize=1)
def backend_version() -> str:
    sha = "unknown"
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=PROJECT_ROOT, capture_output=True, text=True, timeout=2,
        )
        if out.returncode == 0 and out.stdout.strip():
            sha = out.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        pass
    return f"{__version__}+{sha}"
