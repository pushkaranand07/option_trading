"""Docs link checker: relative links must resolve; web links, anchors and code are ignored."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import check_doc_links as cl  # noqa: E402


@pytest.mark.unit
def test_broken_relative_links_are_found_and_others_ignored(tmp_path):
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "b.md").write_text("ok", encoding="utf-8")
    a = tmp_path / "a.md"
    a.write_text("[fine](sub/b.md#part) [missing](sub/c.md) [web](https://x.org/y.md) [anchor](#top) "
                 "`[in code](nope.md)`\n```\n[block](nope2.md)\n```\n", encoding="utf-8")
    assert cl.broken_links([a]) == [(a, "sub/c.md")]
