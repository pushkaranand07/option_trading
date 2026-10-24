"""Check that every relative link in the Markdown docs points to a file that exists.

    python scripts/check_doc_links.py            # docs/ and README.md; exit 1 if any link is broken

Web links, mail links and in-page anchors are not checked; a link's own #anchor is ignored.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[1]
LINK = re.compile(r"\[[^\]]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
CODE = re.compile(r"```.*?```|`[^`\n]*`", re.S)


def broken_links(files: list[Path]) -> list[tuple[Path, str]]:
    bad = []
    for f in files:
        text = CODE.sub("", f.read_text(encoding="utf-8"))
        for target in LINK.findall(text):
            if re.match(r"[a-z]+:", target) or target.startswith("#"):
                continue
            path = unquote(target.split("#", 1)[0])
            if path and not (f.parent / path).exists():
                bad.append((f, target))
    return bad


def main() -> int:
    files = sorted((ROOT / "docs").rglob("*.md")) + [ROOT / "README.md"]
    bad = broken_links(files)
    for f, target in bad:
        print(f"{f.relative_to(ROOT)}: {target}")
    print(f"{len(files)} files, {len(bad)} broken links")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
