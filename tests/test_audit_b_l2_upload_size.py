"""L2: the upload read the whole body before checking its size, and a malformed .xlsx gave a 500. Now a missing or
too-large Content-Length is 413 before any byte is read, the body is read with a running 10 MB cap (a lying
Content-Length is still cut off), and a file that can't be parsed is a 400 with a plain message."""

import asyncio

import pytest

from tests.test_audit_b_support import HEADER, SAME_ORIGIN, client, loopback  # noqa: F401  (fixtures)
from webapp import quant, server

OK = HEADER | SAME_ORIGIN | {"Content-Type": "application/octet-stream"}


@pytest.fixture
def journal_dir(tmp_path, monkeypatch):
    d = tmp_path / "journal"
    monkeypatch.setattr(quant, "JOURNAL_DIR", d)
    return d


def _files(d):
    return sorted(p.name for p in d.iterdir()) if d.exists() else []


def asgi_post(path, query, headers, chunks):
    """Drive the app with raw ASGI messages: returns (status, how many body chunks the app read)."""
    read, sent = {"n": 0}, []

    async def receive():
        if read["n"] < len(chunks):
            read["n"] += 1
            return {"type": "http.request", "body": chunks[read["n"] - 1], "more_body": read["n"] < len(chunks)}
        await asyncio.sleep(3600)                       # no more body: the client waits

    async def send(message):
        sent.append(message)

    scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": "POST", "scheme": "http",
             "path": path, "raw_path": path.encode(), "query_string": query.encode(), "root_path": "",
             "headers": [(k.lower().encode(), v.encode()) for k, v in (headers | {"host": "127.0.0.1:8000"}).items()],
             "client": ("127.0.0.1", 50000), "server": ("127.0.0.1", 8000)}
    asyncio.run(asyncio.wait_for(server.app(scope, receive, send), 30))
    return next(m["status"] for m in sent if m["type"] == "http.response.start"), read["n"]


@pytest.mark.unit
def test_a_missing_content_length_is_413_before_reading(loopback, journal_dir):
    status, chunks_read = asgi_post("/api/journal/upload", "name=t.csv", OK, [b"a,b\n"] * 3)
    assert status == 413 and chunks_read == 0
    assert _files(journal_dir) == []


@pytest.mark.unit
def test_a_content_length_over_10_mb_is_413_before_reading(loopback, journal_dir):
    status, chunks_read = asgi_post("/api/journal/upload", "name=t.csv", OK | {"content-length": str(quant.MAX_UPLOAD + 1)}, [b"x"])
    assert status == 413 and chunks_read == 0
    assert _files(journal_dir) == []


@pytest.mark.unit
def test_a_lying_content_length_is_cut_off_at_the_cap(loopback, journal_dir):
    chunk = b"x" * (1024 * 1024)
    status, chunks_read = asgi_post("/api/journal/upload", "name=t.csv", OK | {"content-length": "100"}, [chunk] * 12)
    assert status == 413 and chunks_read <= 11                     # stopped once past 10 MB, not after all 12
    assert _files(journal_dir) == []


@pytest.mark.unit
def test_a_chunked_upload_without_length_is_refused_through_the_client(client, journal_dir):
    r = client.post("/api/journal/upload?name=t.csv", content=iter([b"a,b\n", b"1,2\n"]), headers=OK)
    assert r.status_code == 413, r.text
    assert _files(journal_dir) == []


@pytest.mark.unit
def test_a_normal_upload_still_saves(client, journal_dir):
    r = client.post("/api/journal/upload?name=t.csv", content=b"a,b\n1,2\n", headers=OK)
    assert r.status_code == 200 and (journal_dir / "t.csv").read_bytes() == b"a,b\n1,2\n"


@pytest.mark.unit
def test_a_malformed_xlsx_is_a_clean_400(client, journal_dir):
    journal_dir.mkdir()
    (journal_dir / "bad.xlsx").write_bytes(b"PK\x03\x04garbage")
    r = client.get("/api/journal", params={"name": "bad.xlsx"})
    assert r.status_code == 400, r.text
    detail = r.json()["detail"]
    assert "bad.xlsx" in detail and "could not be read" in detail
    assert "zip" not in detail.lower()                                     # no library text


@pytest.mark.unit
def test_quant_journal_raises_value_error_for_unparseable_files(journal_dir):
    journal_dir.mkdir()
    (journal_dir / "bad.xlsx").write_bytes(b"PK\x03\x04garbage")
    (journal_dir / "bad.csv").write_bytes(b"\xff\xfe\x00bad\x80\x81")
    for name in ("bad.xlsx", "bad.csv"):
        with pytest.raises(ValueError, match="could not be read"):
            quant.journal(name)


@pytest.mark.unit
def test_the_tradebooks_own_messages_are_kept(journal_dir):
    journal_dir.mkdir()
    (journal_dir / "cols.csv").write_text("foo,bar\n1,2\n", encoding="utf-8")
    with pytest.raises(ValueError, match="No header row"):
        quant.journal("cols.csv")
