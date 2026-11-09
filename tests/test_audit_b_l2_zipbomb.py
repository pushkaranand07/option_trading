"""L2 follow-up: an .xlsx is a zip, and a small one can expand enormously (the verifier's 0.30 MB file expanded to
88 MB: 133 s and 422 MB of RAM in pd.read_excel). Before parsing, the zip's directory is checked: more than 50 MB
uncompressed in total, or any entry compressed more than 100:1, is refused with a ValueError (400) at once."""

import io
import os
import time
import zipfile

import pytest

from tests import test_audit_b_support as support
from webapp import quant

client, loopback = support.client, support.loopback          # the shared fixtures


@pytest.fixture
def journal_dir(tmp_path, monkeypatch):
    d = tmp_path / "journal"
    d.mkdir()
    monkeypatch.setattr(quant, "JOURNAL_DIR", d)
    return d


def _zip(path, entries):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in entries.items():
            z.writestr(name, data)
    path.write_bytes(buf.getvalue())
    return path


@pytest.mark.unit
def test_a_zip_bomb_xlsx_is_refused_fast(journal_dir):
    bomb = _zip(journal_dir / "bomb.xlsx", {"[Content_Types].xml": b"<Types/>", "xl/worksheets/sheet1.xml": b"\0" * (30 * 1024 * 1024)})
    assert bomb.stat().st_size < 200_000
    started = time.perf_counter()
    with pytest.raises(ValueError, match="too large when unpacked"):
        quant.journal("bomb.xlsx")
    assert time.perf_counter() - started < 1.0


@pytest.mark.unit
def test_a_zip_bomb_named_xls_is_refused_fast(journal_dir):
    """pd.read_excel picks openpyxl by content, so the check goes by content too, not by the name."""
    _zip(journal_dir / "bomb.xls", {"[Content_Types].xml": b"<Types/>", "xl/worksheets/sheet1.xml": b"\0" * (30 * 1024 * 1024)})
    started = time.perf_counter()
    with pytest.raises(ValueError, match="too large when unpacked"):
        quant.journal("bomb.xls")
    assert time.perf_counter() - started < 1.0


@pytest.mark.unit
def test_a_genuine_non_zip_xls_reaches_the_normal_parser(journal_dir, monkeypatch):
    from tradingagents.analytics import journal as jr

    ole = journal_dir / "old.xls"
    ole.write_bytes(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\0" * 2048)            # an OLE (binary .xls) header
    quant.check_xlsx_size(ole)                                                     # not a zip: no check, no error
    parsed = []
    monkeypatch.setattr(jr, "read_tradebook", lambda path: parsed.append(path.name) or (_ for _ in ()).throw(ValueError("No header row")))
    with pytest.raises(ValueError, match="No header row"):
        quant.journal("old.xls")
    assert parsed == ["old.xls"]


@pytest.mark.unit
def test_too_much_uncompressed_data_is_refused(journal_dir, monkeypatch):
    monkeypatch.setattr(quant, "XLSX_MAX_UNPACKED", 4096)               # a small limit; random bytes barely compress
    _zip(journal_dir / "big.xlsx", {"xl/worksheets/sheet1.xml": os.urandom(8192)})
    with pytest.raises(ValueError, match="too large when unpacked"):
        quant.journal("big.xlsx")


@pytest.mark.unit
def test_the_route_answers_400(client, journal_dir):
    _zip(journal_dir / "bomb.xlsx", {"xl/worksheets/sheet1.xml": b"\0" * (30 * 1024 * 1024)})
    r = client.get("/api/journal", params={"name": "bomb.xlsx"})
    assert r.status_code == 400 and "too large when unpacked" in r.json()["detail"]


@pytest.mark.unit
def test_a_real_workbook_passes_the_check(journal_dir):
    import pandas as pd

    path = journal_dir / "ok.xlsx"
    pd.DataFrame({"Symbol": ["NIFTY"] * 20, "Qty": [65] * 20, "Price": [101.5] * 20}).to_excel(path, index=False)
    quant.check_xlsx_size(path)                                          # no exception
