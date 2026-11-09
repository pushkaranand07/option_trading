"""Audit-fix follow-ups found by the security verifier (2026-11).

1. dhan_guard checked a normalised path but sent the raw URL: `/marketfeed/ltp/` and `/marketfeed/ltp#/../orders`
   reached the transport (they resolve to the public LTP endpoint, but check and send must not drift apart). Any
   URL whose raw form differs from what was checked is now refused before sending.
2. scripts that load .env themselves ignored TRADINGAGENTS_NO_DOTENV; they now reuse the package's own loader
   (tradingagents._load_env), so one switch turns .env loading off everywhere.
"""

from pathlib import Path

import pytest

from webapp import dhan_guard as g

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def sent(monkeypatch, tmp_path):
    calls = []

    class R:
        status_code = 200

    monkeypatch.setattr(g.requests, "request", lambda method, url, **kw: calls.append((method, url)) or R())
    monkeypatch.setattr(g, "LOG", tmp_path / "dhan_calls.log")
    monkeypatch.setattr(g, "_sleep", lambda s: None)
    monkeypatch.delenv("DHAN_ACCOUNT_ACCESS", raising=False)
    return calls


@pytest.mark.unit
@pytest.mark.parametrize("path", ["/marketfeed/ltp/", "/marketfeed/ltp#/../orders", "/marketfeed/ltp?x=1",
                                  "/orders/../marketfeed/ltp", "/marketfeed/%2E%2E/marketfeed/ltp",
                                  "/marketfeed\\ltp", "/marketfeed/ltp;x", "//marketfeed/ltp"])
def test_a_url_whose_raw_form_differs_from_the_checked_path_is_refused(sent, path):
    with pytest.raises(g.DhanAccountAccessBlocked):
        g.request("POST", path, token="t", client_id="c")
    assert sent == []


@pytest.mark.unit
def test_the_exact_allowed_paths_still_go_through(sent):
    g.request("POST", "/marketfeed/ltp", token="t", client_id="c")
    g.request("GET", "https://images.dhan.co/api-data/api-scrip-master.csv")
    assert [u for _, u in sent] == ["https://api.dhan.co/v2/marketfeed/ltp", "https://images.dhan.co/api-data/api-scrip-master.csv"]


@pytest.mark.unit
@pytest.mark.parametrize("script", ["scripts/morning_plan.py", "scripts/research_rating_stability.py"])
def test_scripts_load_dotenv_only_through_the_package_switch(script):
    text = (ROOT / script).read_text(encoding="utf-8")
    assert "load_dotenv(" not in text, f"{script} loads .env itself, ignoring TRADINGAGENTS_NO_DOTENV"
    assert "_load_env" in text
