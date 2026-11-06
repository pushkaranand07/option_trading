"""The rating stability test's script (docs/rating_stability_test.md): directions, the frozen decision rule, and the
guards (closed market only; nothing the app or the forward test reads is written)."""

import importlib.util
import inspect
from pathlib import Path

import pytest

_PATH = Path(__file__).resolve().parents[1] / "scripts" / "research_rating_stability.py"
_spec = importlib.util.spec_from_file_location("research_rating_stability", _PATH)
rs = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rs)


@pytest.mark.unit
@pytest.mark.parametrize("rating, direction", [("Buy", "bullish"), ("Overweight", "bullish"), ("Hold", "neutral"),
                                               ("Underweight", "bearish"), ("Sell", "bearish"), ("REVIEW", "review")])
def test_each_rating_has_one_direction(rating, direction):
    assert rs.direction(rating) == direction


@pytest.mark.unit
def test_an_unknown_rating_is_an_error():
    with pytest.raises(ValueError):
        rs.direction("Strong buy")


@pytest.mark.unit
@pytest.mark.parametrize("dirs, flips, reading", [
    (["bullish"] * 5, 0, "inconclusive"),
    (["bullish"] * 4 + ["bearish"], 1, "noisy"),
    (["bullish"] * 3 + ["neutral", "bearish"], 2, "noise"),
    (["bullish"] * 3 + ["bearish"] * 2, 2, "noise"),
])
def test_the_five_run_rule_reads_as_written_before_the_runs(dirs, flips, reading):
    assert rs.verdict(dirs) == {"flips": flips, "reading": reading, "majority": "bullish"}


@pytest.mark.unit
def test_there_is_no_rule_yet_for_other_run_counts():
    with pytest.raises(ValueError, match="rule"):
        rs.verdict(["bullish"] * 10)


@pytest.mark.unit
def test_it_refuses_to_run_while_the_market_is_open(monkeypatch, tmp_path):
    monkeypatch.setattr(rs, "_market_open", lambda: True)
    with pytest.raises(SystemExit, match="market"):
        rs.main(["--runs", "5", "--dest", str(tmp_path)])


@pytest.mark.unit
def test_it_never_reaches_the_strategist_the_forward_test_or_the_record():
    src = inspect.getsource(rs)
    for name in ("strategist", "import ai_test", "ai_test.", "trade_record", "save_research", "morning.", "import morning"):
        assert name not in src, name


@pytest.mark.unit
def test_every_run_gets_the_same_lessons_and_never_the_real_memory_log(tmp_path):
    snap = tmp_path / "snap.md"
    snap.write_text("lessons", encoding="utf-8")
    a, b = rs.run_config(snap, tmp_path, 1), rs.run_config(snap, tmp_path, 2)
    assert a["memory_log_path"] != b["memory_log_path"] and a["checkpoint_enabled"] is False
    assert Path(a["memory_log_path"]).read_text(encoding="utf-8") == Path(b["memory_log_path"]).read_text(encoding="utf-8") == "lessons"
    assert str(tmp_path) in a["results_dir"]
