"""The page always loads the current script and style.css: index.html names them with a version taken from the
files themselves, and is itself never cached, so a browser cannot keep running an old script after an update.

The script is ES modules under static/js (entry main.js). main.js and style.css carry ?v= in their tags; every module
main.js imports gets its version from the page's import map, which maps the module's plain URL to its versioned one."""

import json
import re

import pytest

from webapp import server

JS = server.STATIC / "js"


def _page():
    r = server.index()
    return r, r.body.decode("utf-8")


@pytest.mark.unit
def test_the_page_names_its_script_and_styles_with_their_current_version():
    r, html = _page()
    for name in ("js/main.js", "style.css"):
        v = re.search(rf'/static/{re.escape(name)}\?v=(\d+)"', html)
        assert v, name
        assert int(v.group(1)) == int((server.STATIC / name).stat().st_mtime), name
    assert re.search(r'<script type="module" src="/static/js/main\.js\?v=\d+"></script>', html)
    assert "/static/app.js" not in html
    assert r.headers["cache-control"] == "no-cache"


@pytest.mark.unit
def test_every_module_is_named_with_its_current_version_in_the_import_map():
    _, html = _page()
    maps = re.findall(r'<script type="importmap">(.*?)</script>', html, re.S)
    assert len(maps) == 1 and html.index('type="importmap"') < html.index('type="module"')   # the map must come first
    imports = json.loads(maps[0])["imports"]
    files = sorted(JS.glob("*.js"))
    assert files and set(imports) == {f"/static/js/{p.name}" for p in files}
    for p in files:
        assert imports[f"/static/js/{p.name}"] == f"/static/js/{p.name}?v={int(p.stat().st_mtime)}", p.name


@pytest.mark.unit
def test_every_import_is_a_relative_module_file_the_map_covers():
    for p in JS.glob("*.js"):
        for spec in re.findall(r'^import [^;]*? from "([^"]+)";', p.read_text(encoding="utf-8"), re.M):
            assert re.fullmatch(r"\./[\w-]+\.js", spec), f"{p.name}: {spec}"        # no query: the map adds it
            assert (JS / spec[2:]).is_file(), f"{p.name}: {spec}"
