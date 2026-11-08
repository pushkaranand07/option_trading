"""E-docs: the README describes the running forward test (v3), the server's real protections and operating rules,
and .env.example lists every variable the web app reads."""

import re

import pytest

from tests.test_ui_regressions import ROOT

README = (ROOT / "README.md").read_text(encoding="utf-8")
ENV = (ROOT / ".env.example").read_text(encoding="utf-8")


@pytest.mark.unit
def test_the_readme_names_forward_test_v3_and_its_registry():
    assert "docs/ai_strategist_test_v3.json" in README and "reports/ai_test/v3/" in README and "9 Nov 2026" in README
    assert "Forward test of the AI strategist (v2)" not in README and "Forward test v2 registry" not in README


@pytest.mark.unit
def test_the_readme_gives_a_round_test_count_not_an_exact_one():
    assert re.search(r"about 2,\d00 tests", README) and "2,078 tests" not in README


@pytest.mark.unit
def test_the_readme_explains_the_request_guard_instead_of_calling_localhost_safe():
    assert "keep it on localhost" not in README and "Bind to localhost only" not in README
    for s in ("X-Pulse-Request", "Origin", "Host", "127.0.0.1"):
        assert s in README, s


@pytest.mark.unit
def test_the_readme_documents_restart_dhan_guard_and_env_loading():
    assert "Restart the server after every pull or merge" in README
    assert "DHAN_ACCOUNT_ACCESS" in README and "market data only" in README.lower()
    assert "TRADINGAGENTS_NO_DOTENV=1" in README and "repository root" in README


@pytest.mark.unit
@pytest.mark.parametrize("name", ["AZURE_OPENAI_API_KEY", "AZURE_OPENAI_ENDPOINT", "AZURE_OPENAI_DEPLOYMENT_NAME", "DHAN_CLIENT_ID",
                                  "DHAN_ACCESS_TOKEN", "TRADINGAGENTS_NO_DOTENV", "TRADINGAGENTS_REPORTS_DIR", "DHAN_CALL_LOG"])
def test_env_example_lists_each_variable_the_web_app_reads(name):
    assert re.search(rf"^#?{name}=", ENV, re.M), name
    assert not re.search(r"^DHAN_ACCOUNT_ACCESS=", ENV, re.M)                    # never set by this project
