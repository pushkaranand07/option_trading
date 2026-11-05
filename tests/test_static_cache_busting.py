"""The page always loads the current app.js and style.css: index.html names them with a version taken from the
files themselves, and is itself never cached, so a browser cannot keep running an old script after an update."""

import re

import pytest

from webapp import server


@pytest.mark.unit
def test_the_page_names_its_script_and_styles_with_their_current_version():
    r = server.index()
    html = r.body.decode("utf-8")
    for name in ("app.js", "style.css"):
        v = re.search(rf'/static/{re.escape(name)}\?v=(\d+)"', html)
        assert v, name
        assert int(v.group(1)) == int((server.STATIC / name).stat().st_mtime), name
    assert r.headers["cache-control"] == "no-cache"
