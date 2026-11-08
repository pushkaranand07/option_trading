"""Audit M7: every run saves the exact text the ranking LLM was sent (reports/ai_runs/inputs/<run_id>.json), without
touching the fingerprinted ask_rank_llm / ai_ranked: start() passes ai_ranked an ``llm`` that writes the input and
then hands over to the module's ask_rank_llm. All LLMs here are fakes."""

import hashlib
import inspect
import json
import time

import pytest

from webapp import ai_test, strategist as st

V3_FINGERPRINT = "5a5fdbb32e977360b8ed0c9fa45107bbd7ddc315299b825d168f79d4fbc89bd4"
CTX = {"instrument": "NIFTY", "spot": 24350.5, "when": "2026-11-12 10:00", "nested": {"a": [1, 2]}}
CANDS = [{"n": 1, "strategy": "long_call", "legs": [{"strike": 24400.0}], "max_loss_per_lot": 9100.0}]


def _as_ask_rank_llm_builds_it(ctx, candidates):
    # the same expression as in ask_rank_llm (webapp/strategist.py), rebuilt from the recorded arguments
    return (f"DATA:\n{json.dumps(ctx, default=str)}\n\nCANDIDATES (per lot; the app sizes nothing):\n"
            f"{json.dumps(candidates, default=str)}")


@pytest.fixture
def fake_llm(tmp_path, monkeypatch):
    calls = []
    answer = st.RankedAnswer(market_read="m", news_read="n", bias="unclear", picks=[])
    monkeypatch.setattr(st, "_runs_dir", lambda: tmp_path)
    monkeypatch.setattr(st, "ask_rank_llm", lambda ctx, candidates: calls.append((ctx, candidates)) or answer)
    return {"calls": calls, "answer": answer, "dir": tmp_path / "inputs"}


@pytest.mark.unit
def test_the_capture_saves_exactly_what_ask_rank_llm_sends_then_delegates(fake_llm):
    got = st._capture_rank_input("abc123")(CTX, CANDS)
    assert got is fake_llm["answer"] and fake_llm["calls"] == [(CTX, CANDS)]       # the real (here fake) LLM still answers
    saved = json.loads((fake_llm["dir"] / "abc123.json").read_text(encoding="utf-8"))
    ctx, cands = fake_llm["calls"][0]
    assert saved["run_id"] == "abc123" and saved["system"] == st.RANK_SYSTEM
    assert saved["user"] == _as_ask_rank_llm_builds_it(ctx, cands)
    sent = json.dumps([["system", saved["system"]], ["user", saved["user"]]], ensure_ascii=False)
    assert saved["sha256"] == hashlib.sha256(sent.encode("utf-8")).hexdigest()


@pytest.mark.unit
def test_the_capture_uses_the_same_message_format_as_ask_rank_llm():
    def body(f):
        return [ln.strip() for ln in inspect.getsource(f).splitlines() if "DATA:" in ln or "json.dumps(candidates" in ln]

    assert body(st.ask_rank_llm) and body(st.ask_rank_llm) == body(st._rank_user_message)


@pytest.mark.unit
def test_a_failed_save_never_stops_the_ranking(fake_llm, monkeypatch, tmp_path):
    blocker = tmp_path / "file"
    blocker.write_text("x", encoding="utf-8")
    monkeypatch.setattr(st, "_runs_dir", lambda: blocker)                         # inputs/ can't be made under a file
    assert st._capture_rank_input("abc123")(CTX, CANDS) is fake_llm["answer"]


@pytest.mark.unit
def test_start_saves_the_input_under_the_runs_own_id(fake_llm, monkeypatch):
    from webapp import trade_record

    def fake_ai_ranked(symbol, expiry=None, llm=None, agents=None, progress=None, **k):
        (llm or st.ask_rank_llm)(CTX, CANDS)
        return {"symbol": symbol, "expiry": "x", "trades": []}

    monkeypatch.setattr(st, "ai_ranked", fake_ai_ranked)
    monkeypatch.setattr(st, "save_run", lambda res: None)
    monkeypatch.setattr(trade_record, "entry_allowed", lambda *a, **k: "closed")
    monkeypatch.setattr(ai_test, "record", lambda *a, **k: None)
    job_id = st.start("NIFTY")
    for _ in range(200):
        if st.job(job_id)["status"] != "running":
            break
        time.sleep(0.05)
    job = st.job(job_id)
    assert job["status"] == "done", job
    run_id = job["result"]["run_id"]
    saved = json.loads((fake_llm["dir"] / f"{run_id}.json").read_text(encoding="utf-8"))
    assert saved["run_id"] == run_id and saved["user"] == _as_ask_rank_llm_builds_it(CTX, CANDS)


@pytest.mark.unit
def test_the_fingerprint_is_unchanged():
    assert ai_test.prompt_fingerprint() == V3_FINGERPRINT


@pytest.mark.unit
def test_the_capture_hands_over_the_same_objects_unchanged(fake_llm):
    import copy

    ctx, cands = copy.deepcopy(CTX), copy.deepcopy(CANDS)
    before = (copy.deepcopy(ctx), copy.deepcopy(cands))
    st._capture_rank_input("abc123")(ctx, cands)
    got_ctx, got_cands = fake_llm["calls"][0]
    assert got_ctx is ctx and got_cands is cands                                  # the very objects ai_ranked passed
    assert (ctx, cands) == before                                                 # and never mutated


@pytest.mark.unit
@pytest.mark.parametrize("bad", ["../evil", "ABC123", "abc 1", "", r"abc\..\x"])
def test_a_run_id_that_is_not_hex_saves_nothing_but_still_ranks(fake_llm, tmp_path, bad):
    assert st._capture_rank_input(bad)(CTX, CANDS) is fake_llm["answer"]
    assert fake_llm["calls"] == [(CTX, CANDS)]
    assert not list(tmp_path.rglob("*.json"))
