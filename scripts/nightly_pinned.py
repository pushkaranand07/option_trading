"""Run the nightly update from a dedicated git worktree pinned to main (docs/PA_46).

    <main checkout>\\.venv\\Scripts\\pythonw.exe -W ignore <worktree>\\scripts\\nightly_pinned.py --log <file>
    python scripts/nightly_pinned.py --install        # from the main checkout, after this file is on main

The task runs this file from the worktree, whose HEAD is detached at origin/main. Whatever branch the main checkout has out, the
code that runs is main's. Each run moves the worktree to the latest origin/main first; if the fetch fails, it runs the last main commit
it has and says so. A worktree that is not pinned refuses to run. What the job collects is unchanged (scripts/quant_daily_update.py).
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

WORKTREE_NAME = "TradingAgents-nightly"
TASK = "TradingAgents quant daily update"


class NotPinned(RuntimeError):
    """The worktree is not a detached worktree on a commit of origin/main."""


def _no_window() -> int:
    return getattr(subprocess, "CREATE_NO_WINDOW", 0)


def git(root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, creationflags=_no_window())


def _out(root: Path, *args: str) -> str:
    return git(root, *args).stdout.strip()


def main_checkout(worktree: Path) -> Path:
    """The checkout that owns this worktree's repository: where .env and reports/ live."""
    common = Path(_out(worktree, "rev-parse", "--path-format=absolute", "--git-common-dir"))
    return common.parent


def refresh(worktree: Path) -> str:
    """Move to the latest origin/main, discarding the tracker's local rewrite. Returns a note if the fetch failed."""
    fetched = git(worktree, "fetch", "origin", "main")
    note = "" if fetched.returncode == 0 else f"fetch failed, running the last main commit held: {fetched.stderr.strip()}"
    moved = git(worktree, "checkout", "--detach", "--force", "origin/main")
    if moved.returncode != 0:
        raise NotPinned(f"could not move to origin/main: {moved.stderr.strip()}")
    return note


def check_pinned(worktree: Path) -> str:
    """The commit that will run; raises unless this is a linked worktree, detached, exactly at origin/main."""
    if _out(worktree, "rev-parse", "--absolute-git-dir") == _out(worktree, "rev-parse", "--path-format=absolute", "--git-common-dir"):
        raise NotPinned(f"{worktree} is the main checkout, not a dedicated worktree")
    if git(worktree, "symbolic-ref", "-q", "HEAD").returncode == 0:
        raise NotPinned(f"{worktree} has a branch checked out; it must be detached")
    head, main = _out(worktree, "rev-parse", "HEAD"), _out(worktree, "rev-parse", "origin/main")
    if not head or head != main:
        raise NotPinned(f"HEAD {head} is not origin/main {main}")
    return head


def pinned_env(worktree: Path, base: dict[str, str] | None = None) -> dict[str, str]:
    """Imports resolve to the worktree first. Secrets stay in the main checkout's .env, read here and never copied; generated pages
    stay in its reports/, where the web app reads them."""
    from dotenv import dotenv_values

    primary = main_checkout(worktree)
    env = {k: v for k, v in dotenv_values(primary / ".env").items() if v is not None}
    env |= dict(os.environ if base is None else base)
    env["PYTHONPATH"] = str(worktree)
    env["TRADINGAGENTS_REPORTS_DIR"] = str(primary / "reports")
    return env


def run(worktree: Path, log: Path | None, extra: list[str]) -> int:
    def say(text: str) -> None:
        print(text, flush=True)
        if log:
            log.parent.mkdir(parents=True, exist_ok=True)
            with log.open("a", encoding="utf-8") as fh:
                fh.write(text + "\n")

    try:
        note = refresh(worktree)
        commit = check_pinned(worktree)
    except NotPinned as exc:
        say(f"\n==== {datetime.now():%Y-%m-%d %H:%M:%S} nightly refused: {exc}")
        return 2
    say(f"\n==== {datetime.now():%Y-%m-%d %H:%M:%S} nightly pinned at main {commit[:12]} in {worktree}" + (f"; {note}" if note else ""))
    cmd = [sys.executable, "-W", "ignore", "scripts/quant_daily_update.py", *extra]
    if log:
        cmd += ["--log", str(log)]
    return subprocess.run(cmd, cwd=worktree, env=pinned_env(worktree), creationflags=_no_window()).returncode


def install(primary: Path) -> int:
    """Create the worktree and point the scheduled task at it. Run once, from the main checkout, after this file is on main."""
    worktree = primary.parent / WORKTREE_NAME
    git(primary, "fetch", "origin", "main")
    if not worktree.exists():
        added = git(primary, "worktree", "add", "--detach", str(worktree), "origin/main")
        if added.returncode != 0:
            print(added.stderr)
            return 1
    commit = check_pinned(worktree)
    py = primary / ".venv" / "Scripts" / "pythonw.exe"
    log = Path.home() / ".tradingagents" / "cache" / "quant" / "daily_update.log"
    action = f'"{py}" -W ignore "{worktree / "scripts" / "nightly_pinned.py"}" --log "{log}"'
    done = subprocess.run(["schtasks", "/Change", "/TN", TASK, "/TR", action], capture_output=True, text=True)
    print(done.stdout or done.stderr)
    print(f"worktree {worktree} at main {commit[:12]}; task runs: {action}")
    return done.returncode


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--log", type=Path)
    parser.add_argument("--dry-run", action="store_true", help="check the pin and list the steps; no step runs")
    parser.add_argument("--install", action="store_true")
    args = parser.parse_args()
    here = Path(__file__).resolve().parents[1]
    if args.install:
        return install(here)
    return run(here, args.log, ["--dry-run"] if args.dry_run else [])


if __name__ == "__main__":
    raise SystemExit(main())
