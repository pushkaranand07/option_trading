"""p3-appjs verifier's blocker (audit 2026-11): planchart.js used lineOpts without importing it, so the Plan tab's live
charts threw "lineOpts is not defined" in a real browser. The harness hid it because it put every module's exports
on the sandbox's global object, where a forgotten import was found anyway. Exports now live on a separate object
used only to evaluate the test's expression, so a module that forgets an import fails here as in the browser."""

import pytest

from tests.test_ui_regressions import pytestmark as _needs_node, render

DRAW = "(() => { try { planChart('NIFTY'); return 'drawn'; } catch (e) { return String(e); } })()"


@pytest.mark.unit
@_needs_node
def test_the_plan_chart_draws_without_a_missing_import():
    out = render(DRAW)
    assert "is not defined" not in out, out


@pytest.mark.unit
@_needs_node
def test_module_exports_are_not_globals_of_the_sandbox():
    # A module can only see what it imports: an export of another module is not reachable as a bare global.
    assert render("String(typeof globalThis.lineOpts)") == "undefined"
    assert render("String(typeof lineOpts)") == "object"           # the test expression still sees every export
