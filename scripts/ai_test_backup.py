"""Dated copy of the forward test's registry and saved chains, with a checksum file. Run by hand only (docs/ai_test_backup_restore.md).

    python scripts/ai_test_backup.py --dest <folder you chose>
    python scripts/ai_test_backup.py --verify <backup folder>

No upload and no schedule. A destination inside the repo is refused. It never overwrites an earlier backup.
"""

from __future__ import annotations

import argparse
import hashlib
import shutil
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "reports" / "ai_test"
SUMS = "SHA256SUMS.txt"
ITEMS = ("registry.jsonl", "chains", "power.json")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify(folder: Path) -> list[str]:
    """Problems found in a backup; empty means every file matches its checksum and nothing is extra."""
    folder = Path(folder)
    sums = folder / SUMS
    if not sums.exists():
        return [f"no {SUMS}"]
    problems, listed = [], set()
    for line in sums.read_text(encoding="utf-8").splitlines():
        digest, rel = line.split("  ", 1)
        listed.add(rel)
        target = folder / rel
        if not target.exists():
            problems.append(f"missing: {rel}")
        elif _sha(target) != digest:
            problems.append(f"changed: {rel}")
    for p in folder.rglob("*"):
        if p.is_file() and p.name != SUMS and p.relative_to(folder).as_posix() not in listed:
            problems.append(f"not in the checksum file: {p.relative_to(folder).as_posix()}")
    return problems


def backup(dest: Path, source: Path = SOURCE, repo: Path = ROOT, now: datetime | None = None) -> Path:
    dest = Path(dest).resolve()
    if not dest.is_dir():
        raise ValueError(f"{dest} is not an existing folder")
    if dest == repo.resolve() or repo.resolve() in dest.parents:
        raise ValueError("the backup must be outside the repo")
    if not source.exists():
        raise ValueError(f"nothing to back up: {source} does not exist")
    target = dest / f"ai_test_backup_{(now or datetime.now()):%Y%m%d_%H%M%S}"
    target.mkdir()      # raises if it exists: an earlier backup is never overwritten
    for name in ITEMS:
        item = source / name
        if item.is_dir():
            shutil.copytree(item, target / name)
        elif item.exists():
            shutil.copy2(item, target / name)
    lines = [f"{_sha(p)}  {p.relative_to(target).as_posix()}" for p in sorted(target.rglob("*")) if p.is_file()]
    (target / SUMS).write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    problems = verify(target)
    if problems:
        raise ValueError(f"backup did not verify: {problems}")
    return target


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dest", type=Path)
    parser.add_argument("--verify", type=Path)
    args = parser.parse_args()
    if bool(args.dest) == bool(args.verify):
        parser.error("give --dest or --verify")
    if args.verify:
        problems = verify(args.verify)
        print("OK" if not problems else "\n".join(problems))
        return 1 if problems else 0
    print(backup(args.dest))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
