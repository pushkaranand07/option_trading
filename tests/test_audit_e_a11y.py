"""E-a11y (Lighthouse): normal text meets WCAG AA contrast (4.5:1) in both themes, and the page makes no request that
is sure to fail on load (no favicon.ico 404; no Dhan-only call when /api/status says dhan: false; no NSE chain poll
outside the live session), because the browser logs each failed request as a console error."""

import json
import re

import pytest

from tests.test_ui_regressions import ROOT, app_source, pytestmark as _needs_node, render

STATIC = ROOT / "webapp" / "static"
CSS = (STATIC / "style.css").read_text(encoding="utf-8")


def tokens(block_start: str) -> dict:
    i = CSS.index(block_start)
    body = CSS[CSS.index("{", i + len(block_start) - 1) + 1:CSS.index("}", i)]
    return dict(re.findall(r"--([\w-]+):\s*([^;]+);", body))


LIGHT = tokens(":root {")
DARK = LIGHT | tokens(':root[data-theme="dark"] {')
DARK_MEDIA = LIGHT | tokens(':root:not([data-theme="light"]) {')


def rgba(v: str):
    v = v.strip()
    if v.startswith("#"):
        if len(v) == 4:                                                          # #fff -> #ffffff
            v = "#" + "".join(ch * 2 for ch in v[1:])
        return tuple(int(v[i:i + 2], 16) for i in (1, 3, 5)) + (1.0,)
    r, g, b, a = (x.strip() for x in v[v.index("(") + 1:v.index(")")].split(","))
    return int(r), int(g), int(b), float(a)


def over(fg, bg):
    """fg (maybe translucent) painted over an opaque bg."""
    a = fg[3]
    return tuple(round(f * a + b * (1 - a)) for f, b in zip(fg[:3], bg[:3], strict=True)) + (1.0,)


def ratio(fg, bg):
    def lum(c):
        ch = [x / 255 for x in c[:3]]
        r, g, b = (x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4 for x in ch)
        return 0.2126 * r + 0.7152 * g + 0.0722 * b
    hi, lo = sorted((lum(fg), lum(bg)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def pairs(t: dict):
    """(what, foreground, background) for the text the page draws, backgrounds composited as the browser does."""
    c = {k: rgba(v) for k, v in t.items() if v.strip().startswith(("#", "rgba"))}
    out = []
    for surf in ("panel", "bg", "panel-2"):
        for fg in ("text", "muted", "up", "down", "warn"):
            out.append((f"{fg} on {surf}", c[fg], c[surf]))
    for tone in ("up", "down", "warn"):                              # badges, pills and notices: tone text on its soft tint
        for surf in ("panel", "bg"):
            out.append((f"{tone} on {tone}-soft over {surf}", c[tone], over(c[f"{tone}-soft"], c[surf])))
    for bg, fg in (("brand", "on-brand"), ("up", "on-brand"), ("down", "on-down")):   # buttons, logo, BUY / SELL tags
        out.append((f"{fg} on {bg}", c[fg], c[bg]))
    for fg in ("ema9-text", "ema21-text"):                           # the chart readout's average values
        out.append((f"{fg} on panel", c[fg], c["panel"]))
    out.append(("ema9-text on atm", c["ema9-text"], c["atm"]))       # the option chain's ATM strike
    bar = float(re.search(r"\.oc \.bar \{[^}]*opacity:\s*([\d.]+)", CSS).group(1))    # OI bars drawn under the numbers
    for fg, under in (("up", "down"), ("down", "up")):
        out.append((f"{fg} on a full {under} OI bar", c[fg], over(c[under][:3] + (bar,), c["panel"])))
    return out


@pytest.mark.unit
@pytest.mark.parametrize("theme", ["light", "dark", "dark (system)"])
def test_normal_text_has_at_least_4_5_to_1_contrast(theme):
    t = {"light": LIGHT, "dark": DARK, "dark (system)": DARK_MEDIA}[theme]
    low = [f"{what} {ratio(fg, bg):.2f}" for what, fg, bg in pairs(t) if ratio(fg, bg) < 4.5]
    assert not low, low


@pytest.mark.unit
def test_text_on_coloured_fills_uses_the_on_colour_tokens_not_hard_white():
    for rule in re.findall(r"[^{}]+\{[^}]*\}", CSS):
        if re.search(r"background:\s*var\(--(brand|up|down)\)", rule):
            assert "color: #fff" not in rule, rule.strip()


@pytest.mark.unit
def test_the_page_declares_an_icon_so_the_browser_does_not_request_favicon_ico():
    page = (STATIC / "index.html").read_text(encoding="utf-8")
    assert re.search(r'<link rel="icon" href="data:', page)


@pytest.mark.unit
@_needs_node
def test_without_dhan_the_options_tab_calls_no_dhan_only_endpoint():
    out = json.loads(render("""
      var SENT = []; fetch = (p) => { SENT.push(p); return new Promise(() => {}); };
      S.status = { dhan: false }; S.indices = [{ symbol: 'NIFTY', name: 'NIFTY 50' }]; S.sym = 'NIFTY'; S.expiry = '13-Nov-2026';
      loadOptions(); loadChain(); JSON.stringify(SENT)"""))
    assert not [p for p in out if p.startswith(("/api/expiries", "/api/optionchain"))], out
    with_dhan = json.loads(render("""
      var SENT = []; fetch = (p) => { SENT.push(p); return new Promise(() => {}); };
      S.status = { dhan: true }; S.indices = [{ symbol: 'NIFTY', name: 'NIFTY 50' }]; S.sym = 'NIFTY';
      loadOptions(); JSON.stringify(SENT)"""))
    assert with_dhan == ["/api/expiries/NIFTY"]


@pytest.mark.unit
@_needs_node
def test_the_nse_chain_is_not_polled_outside_the_live_session():
    out = json.loads(render("""
      var SENT = []; fetch = (p) => { SENT.push(p); return new Promise(() => {}); };
      S.tab = 'plan'; S.sym = 'NIFTY'; S.morning = { session: null, indices: { NIFTY: {} } };
      pollNseChains(); JSON.stringify(SENT)"""))
    assert out == []
    polled = json.loads(render("JSON.stringify(poller.tasks.filter((t) => t.fn === pollNseChains).map((t) => [t.every, t.when()]))"))
    assert polled == [[15000, True]]          # the page's scheduler calls it every 15 s; it decides itself whether to fetch


# A rating's verdict box: one class per tone, each naming its fill and its text colour.
VERDICT = re.compile(r"\.verdict\.v-([\w-]+)\s*\{[^}]*background:\s*var\(--([\w-]+)\);[^}]*color:\s*var\(--([\w-]+)\)")


@pytest.mark.unit
def test_every_rating_verdict_has_a_tone_class_whose_text_has_4_5_to_1_contrast_in_both_themes():
    app = app_source()
    tones = set(re.findall(r'"(\w+)"', re.search(r"const RATING_TONES = \{([^}]*)\}", app).group(1))) | {"muted"}   # unknown: muted
    rules = {tone: (bg, fg) for tone, bg, fg in VERDICT.findall(CSS)}
    assert tones <= set(rules), tones - set(rules)
    assert 'class="verdict v-${' in app and "background:${cssVar(RATING" not in app      # no inline fill with white text
    assert not re.search(r"\.verdict\s*\{[^}]*color:\s*#fff", CSS)
    for theme, t in (("light", LIGHT), ("dark", DARK), ("dark (system)", DARK_MEDIA)):
        c = {k: rgba(v) for k, v in t.items() if v.strip().startswith(("#", "rgba"))}
        low = [f"{theme} {tone}: {ratio(c[fg], c[bg]):.2f}" for tone, (bg, fg) in rules.items() if ratio(c[fg], c[bg]) < 4.5]
        assert not low, low
