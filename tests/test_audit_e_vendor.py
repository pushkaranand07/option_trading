"""Audit L3: the page's three libraries are served from webapp/static/vendor (exact pinned versions, hashes recorded in
vendor/README.md), not from a CDN, and the page still starts when the chart library is missing."""

import base64
import hashlib
import json
import os
import re
import shutil
import subprocess

import pytest

from tests.test_ui_regressions import ROOT

STATIC = ROOT / "webapp" / "static"
VENDOR = STATIC / "vendor"
LIBS = ("lightweight-charts-4.2.0.standalone.production.js", "marked-12.0.2.min.js", "purify-3.1.6.min.js")


@pytest.mark.unit
def test_the_page_loads_its_libraries_from_static_vendor_and_no_cdn_script():
    page = (STATIC / "index.html").read_text(encoding="utf-8")
    scripts = re.findall(r'<script[^>]*\bsrc="([^"]+)"', page)
    assert not [s for s in scripts if s.startswith(("http:", "https:", "//"))], scripts
    for lib in LIBS:
        assert f'src="/static/vendor/{lib}"' in page, lib


@pytest.mark.unit
def test_each_vendor_file_matches_the_sha384_recorded_in_its_readme():
    readme = (VENDOR / "README.md").read_text(encoding="utf-8")
    for lib in LIBS:
        digest = "sha384-" + base64.b64encode(hashlib.sha384((VENDOR / lib).read_bytes()).digest()).decode()
        row = next((line for line in readme.splitlines() if lib in line and "sha384-" in line), "")
        assert digest in row, f"{lib}: {digest} not recorded in vendor/README.md"


def run_without(globals_: str, expr: str) -> subprocess.CompletedProcess:
    return subprocess.run(["node", str(ROOT / "tests" / "js" / "render.js"), expr], input="[]", capture_output=True, text=True,
                          encoding="utf-8", timeout=60, env=os.environ | {"RENDER_DROP": globals_})


@pytest.mark.unit
@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is needed to run the page's script")
def test_a_missing_chart_library_leaves_the_page_running_and_says_the_chart_is_unavailable():
    out = run_without("LightweightCharts", "JSON.stringify({ chart: chartProblem(), banners: bannerTexts({}) })")
    assert out.returncode == 0, out.stderr                                   # the script did not stop at the top level
    shown = json.loads(out.stdout)
    assert "chart unavailable" in shown["chart"].lower() and shown["banners"]["code"] is None


@pytest.mark.unit
@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is needed to run the page's script")
def test_missing_markdown_libraries_show_the_text_escaped_instead_of_failing():
    out = run_without("marked,DOMPurify", "mdHtml('**hi** <img src=x onerror=alert(1)>')")
    assert out.returncode == 0, out.stderr
    assert "<img" not in out.stdout and "**hi**" in out.stdout
