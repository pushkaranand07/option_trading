"""H4 (audit 2026-11): the package loads only the repository's own .env. It never walks up from the working
directory (a worktree or copy under the repo, or any folder below another project, must not inherit its keys), and
it loads nothing when TRADINGAGENTS_NO_DOTENV=1 or under pytest."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PROBE = "import os, tradingagents; print('PROBE=' + str(os.environ.get('TA_H4_PROBE')))"
BLANK = dict.fromkeys(("AZURE_OPENAI_API_KEY", "AZURE_OPENAI_ENDPOINT", "AZURE_OPENAI_DEPLOYMENT_NAME", "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GOOGLE_API_KEY", "DHAN_CLIENT_ID", "DHAN_ACCESS_TOKEN"), "")


def _run(cwd: Path, **env) -> str:
    e = {k: v for k, v in os.environ.items() if k != "TA_H4_PROBE"} | BLANK | {"PYTHONPATH": str(ROOT)} | env
    out = subprocess.run([sys.executable, "-c", PROBE], cwd=cwd, env=e, capture_output=True, text=True, timeout=120)
    assert out.returncode == 0, out.stderr
    return out.stdout.strip().splitlines()[-1]


@pytest.mark.unit
def test_a_dotenv_in_a_parent_folder_of_the_working_directory_is_not_loaded(tmp_path):
    (tmp_path / ".env").write_text("TA_H4_PROBE=leaked-from-parent\n", encoding="utf-8")
    child = tmp_path / "worktree" / "deep"
    child.mkdir(parents=True)
    assert _run(child) == "PROBE=None"


@pytest.mark.unit
def test_the_repo_dotenv_is_loaded_and_the_switch_turns_it_off(tmp_path, monkeypatch):
    import tradingagents

    root = tmp_path / "repo"
    root.mkdir()
    (root / ".env").write_text("TA_H4_PROBE=from-root\n", encoding="utf-8")
    monkeypatch.delenv("TA_H4_PROBE", raising=False)
    assert tradingagents._load_env(root=root, environ={"TRADINGAGENTS_NO_DOTENV": "1"}, modules={}) == []
    assert "TA_H4_PROBE" not in os.environ
    assert tradingagents._load_env(root=root, environ={}, modules={"pytest": object()}) == []
    assert "TA_H4_PROBE" not in os.environ
    assert tradingagents._load_env(root=root, environ={}, modules={}) == [root / ".env"]
    assert os.environ["TA_H4_PROBE"] == "from-root"


@pytest.mark.unit
def test_an_exported_value_is_never_overridden(tmp_path, monkeypatch):
    import tradingagents

    (tmp_path / ".env").write_text("TA_H4_PROBE=from-file\n", encoding="utf-8")
    monkeypatch.setenv("TA_H4_PROBE", "exported")
    tradingagents._load_env(root=tmp_path, environ={}, modules={})
    assert os.environ["TA_H4_PROBE"] == "exported"
