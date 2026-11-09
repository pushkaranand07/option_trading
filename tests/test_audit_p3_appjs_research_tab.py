"""P3: the Research tab loads /api/research. In the single app.js a second function named loadResearch (the Plan tab's,
loadResearch(sym)) replaced the tab's own, so opening the tab asked for /api/strategy/research/undefined and the tab
stayed empty. The modules keep the two apart."""

import json

import pytest

from tests.test_ui_regressions import pytestmark as _needs_node, render

pytestmark = _needs_node

OPEN = """
var SENT = []; fetch = (p) => { SENT.push(p); return new Promise(() => {}); };
showTab(ARGS[0], true); JSON.stringify(SENT)"""


@pytest.mark.unit
def test_opening_the_research_tab_asks_for_the_research_results():
    assert json.loads(render(OPEN, "research")) == ["/api/research"]


@pytest.mark.unit
def test_the_research_tab_shows_what_the_server_sent():
    shown = render("""
      var HTML = {}; document = { querySelector: (s) => (HTML[s] ||= { innerHTML: '' }) };
      fetch = async () => ({ ok: true, status: 200, json: async () => ARGS[0] });
      loadResearchTab().then(() => HTML['#researchBody'].innerHTML)""",
                   {"in_use": [{"name": "GARCH", "evidence": "beat history", "use": "stops"}], "tested": [], "paper": [],
                    "approved": [], "daily_job": None, "freshness": None})
    assert "GARCH" in shown and "none has passed yet" in shown
