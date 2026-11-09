"""Audit follow-up (A-bom): a trades.json saved by Notepad or PowerShell 5.1 starts with a UTF-8 BOM. It was read
as damaged (every write refused). It now loads normally; the record keeps writing plain UTF-8 (no BOM)."""

import json

import pytest

from tests.test_trade_record import RESULT
from webapp import trade_record as tr


@pytest.mark.unit
def test_a_bom_file_with_valid_json_loads_and_is_saved_back_without_a_bom(tmp_path, monkeypatch):
    monkeypatch.setattr(tr, "STORE", tmp_path / "trades.json")
    monkeypatch.setattr(tr, "_market_open", lambda *a: True)
    t = tr.take(RESULT)
    tr.STORE.write_bytes(b"\xef\xbb\xbf" + tr.STORE.read_bytes())     # as Notepad saves it
    assert [r["id"] for r in tr._load()] == [t["id"]] and tr.store_problem() is None
    tr.delete(t["id"])
    assert not tr.STORE.read_bytes().startswith(b"\xef\xbb\xbf") and json.loads(tr.STORE.read_text(encoding="utf-8")) == []
    assert not list(tmp_path.glob("trades.json.corrupt-*"))
