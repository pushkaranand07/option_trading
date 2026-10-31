"""The nightly job runs main's code from a dedicated worktree, whatever the main checkout has out (scripts/nightly_pinned.py)."""

import importlib.util
import json
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("nightly_pinned", ROOT / "scripts" / "nightly_pinned.py")
np_ = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(np_)

JOB = """import json, os, sys
from pathlib import Path
import marker
Path(os.environ["OUT_FILE"]).write_text(json.dumps({"version": "%s", "script": __file__, "marker": marker.__file__, "reports": os.environ.get("TRADINGAGENTS_REPORTS_DIR"),
    "secret": os.environ.get("NIGHTLY_TEST_SECRET"), "args": sys.argv[1:], "cwd": os.getcwd()}))
"""


def _git(root, *args):
    subprocess.run(["git", "-C", str(root), "-c", "user.name=t", "-c", "user.email=t@t", *args], check=True, capture_output=True)


def _commit(root, version, message):
    (root / "scripts").mkdir(exist_ok=True)
    (root / "scripts" / "quant_daily_update.py").write_text(JOB % version, encoding="utf-8")
    (root / "marker.py").write_text(f"# {version}\n", encoding="utf-8")
    _git(root, "add", "scripts", "marker.py")
    _git(root, "commit", "-m", message)


@pytest.fixture
def repo(tmp_path, monkeypatch):
    """An origin, a main checkout, and a worktree pinned to origin/main."""
    origin, primary, worktree = tmp_path / "origin", tmp_path / "primary", tmp_path / "wt"
    primary.mkdir()
    _git(primary, "init", "-b", "main")
    _commit(primary, "main-1", "first")
    subprocess.run(["git", "clone", "--bare", str(primary), str(origin)], check=True, capture_output=True)
    _git(primary, "remote", "add", "origin", str(origin))
    _git(primary, "fetch", "origin")
    _git(primary, "worktree", "add", "--detach", str(worktree), "origin/main")
    (primary / ".env").write_text("NIGHTLY_TEST_SECRET=from-env-file\n", encoding="utf-8")
    monkeypatch.setenv("OUT_FILE", str(tmp_path / "out.json"))
    monkeypatch.delenv("NIGHTLY_TEST_SECRET", raising=False)
    return {"primary": primary, "worktree": worktree, "out": tmp_path / "out.json", "tmp": tmp_path}


@pytest.mark.unit
def test_a_research_branch_in_the_main_checkout_cannot_change_what_runs(repo):
    primary = repo["primary"]
    _git(primary, "switch", "-c", "research/something")
    _commit(primary, "research-branch", "not on main")
    assert np_.run(repo["worktree"], None, []) == 0
    done = json.loads(repo["out"].read_text())
    assert done["version"] == "main-1"
    assert Path(done["script"]).resolve().parent.parent == repo["worktree"].resolve()
    assert Path(done["marker"]).resolve().parent == repo["worktree"].resolve()     # imports resolve to the worktree


@pytest.mark.unit
def test_uncommitted_work_in_the_main_checkout_cannot_change_what_runs(repo):
    (repo["primary"] / "scripts" / "quant_daily_update.py").write_text("raise SystemExit(9)\n", encoding="utf-8")
    assert np_.run(repo["worktree"], None, []) == 0
    assert json.loads(repo["out"].read_text())["version"] == "main-1"


@pytest.mark.unit
def test_each_run_moves_to_the_latest_main(repo):
    other = repo["tmp"] / "other"
    subprocess.run(["git", "clone", str(repo["tmp"] / "origin"), str(other)], check=True, capture_output=True)
    _commit(other, "main-2", "merged")
    _git(other, "push", "origin", "main")
    assert np_.run(repo["worktree"], None, []) == 0
    assert json.loads(repo["out"].read_text())["version"] == "main-2"


@pytest.mark.unit
def test_a_local_change_in_the_worktree_is_discarded_before_the_run(repo):
    (repo["worktree"] / "marker.py").write_text("raise SystemExit(9)\n", encoding="utf-8")
    assert np_.run(repo["worktree"], None, []) == 0
    assert json.loads(repo["out"].read_text())["version"] == "main-1"


@pytest.mark.unit
def test_a_failed_fetch_runs_the_last_main_commit_and_says_so(repo):
    _git(repo["worktree"], "remote", "set-url", "origin", str(repo["tmp"] / "gone"))
    log = repo["tmp"] / "log.txt"
    assert np_.run(repo["worktree"], log, []) == 0
    assert json.loads(repo["out"].read_text())["version"] == "main-1"
    assert "fetch failed" in log.read_text(encoding="utf-8")


@pytest.mark.unit
def test_the_main_checkout_itself_is_refused(repo):
    log = repo["tmp"] / "log.txt"
    assert np_.run(repo["primary"], log, []) == 2
    assert not repo["out"].exists()
    assert "main checkout" in log.read_text(encoding="utf-8")


@pytest.mark.unit
def test_a_worktree_on_a_branch_or_off_main_is_not_pinned(repo):
    wt = repo["worktree"]
    assert np_.check_pinned(wt)
    _git(wt, "switch", "-c", "feature")
    with pytest.raises(np_.NotPinned, match="branch"):
        np_.check_pinned(wt)
    _git(wt, "switch", "--detach")
    _commit(wt, "off-main", "not on main")
    with pytest.raises(np_.NotPinned, match="not origin/main"):
        np_.check_pinned(wt)


@pytest.mark.unit
def test_secrets_and_reports_come_from_the_main_checkout_and_are_not_copied(repo):
    assert np_.run(repo["worktree"], None, ["--dry-run"]) == 0
    done = json.loads(repo["out"].read_text())
    assert done["secret"] == "from-env-file" and done["args"] == ["--dry-run"]
    assert Path(done["reports"]).resolve() == (repo["primary"] / "reports").resolve()
    assert Path(done["cwd"]).resolve() == repo["worktree"].resolve()
    assert not (repo["worktree"] / ".env").exists()


@pytest.mark.unit
def test_the_job_itself_is_unchanged_in_what_it_runs():
    text = (ROOT / "scripts" / "nightly_pinned.py").read_text(encoding="utf-8")
    assert '"scripts/quant_daily_update.py"' in text
    for word in ("nseindia", "yfinance", "requests", "quant_backfill"):
        assert word not in text, word


@pytest.mark.unit
def test_the_market_map_page_goes_to_the_directory_it_is_told(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADINGAGENTS_REPORTS_DIR", str(tmp_path))
    spec = importlib.util.spec_from_file_location("market_map_for_test", ROOT / "scripts" / "market_map.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    assert tmp_path / "market_map" == m.OUT
