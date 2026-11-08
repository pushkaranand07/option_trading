"""TradingAgents: multi-agent LLM financial trading framework."""

__version__ = "0.7.0"

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent


def _load_env(root: Path = ROOT, environ=os.environ, modules=sys.modules) -> list[Path]:
    """Load the repository's own .env (and .env.enterprise) at package import, so DEFAULT_CONFIG's env-var overlay
    and every LLM client see the user's keys whichever entry point started the process. Only ``root`` is read: no
    walk up from the working directory, so a worktree, copy or folder below another project never inherits its keys
    (audit H4). Nothing is loaded when TRADINGAGENTS_NO_DOTENV=1 or under pytest. Exported values are never overridden."""
    if environ.get("TRADINGAGENTS_NO_DOTENV") == "1" or "pytest" in modules:
        return []
    loaded = []
    for name in (".env", ".env.enterprise"):
        path = root / name
        if path.is_file():
            load_dotenv(path, override=False)
            loaded.append(path)
    return loaded


_load_env()
