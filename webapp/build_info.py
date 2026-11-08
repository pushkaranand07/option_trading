"""What code this server is running: the git commit checked out when it started, and when it started.

A running server keeps the Python it loaded; after a merge or a pull it runs old code until it is restarted (the
2026-11-04 15:33 row and the duplicates were written that way). Each new trade row records both values, and the page
warns while the commit checked out differs from the one the server started on."""

from __future__ import annotations

import subprocess
from pathlib import Path

from webapp import timeutil

ROOT = Path(__file__).resolve().parent.parent


def repo_head() -> str | None:
    """The commit checked out now, or None when git is not available."""
    try:
        out = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return None
    return (out.stdout.strip() or None) if out.returncode == 0 else None


CODE_VERSION = repo_head()                                   # read once, when the server starts
STARTED_AT = timeutil.now_ist().replace(tzinfo=None).isoformat(timespec="seconds")   # IST wall time (L6), no offset


def status() -> dict:
    """The running commit, the checked-out commit, when the server started, and whether a restart is due."""
    repo = repo_head()
    return {"running": CODE_VERSION, "repo": repo, "started_at": STARTED_AT,
            "stale": bool(CODE_VERSION and repo and repo != CODE_VERSION)}
