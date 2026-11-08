"""M2: the journal upload took a raw body of any Content-Type, so a cross-site form (text/plain) could write a file.
Now it needs the H2 header and a local Origin, and a Content-Type of application/octet-stream (what the page sends),
text/csv or the .xlsx type; anything else is 415 and nothing is written."""

import pytest

from tests.test_audit_b_support import HEADER, SAME_ORIGIN, client, loopback  # noqa: F401  (fixtures)
from webapp import quant

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@pytest.fixture
def journal_dir(tmp_path, monkeypatch):
    d = tmp_path / "journal"
    monkeypatch.setattr(quant, "JOURNAL_DIR", d)
    return d


def _files(d):
    return sorted(p.name for p in d.iterdir()) if d.exists() else []


@pytest.mark.unit
def test_a_cross_site_text_plain_post_writes_nothing(client, journal_dir):
    r = client.post("/api/journal/upload?name=evil.csv", content=b"a,b\n1,2\n",
                    headers={"Content-Type": "text/plain", "Origin": "http://evil.example"})
    assert r.status_code == 403, r.text
    assert _files(journal_dir) == []


@pytest.mark.unit
@pytest.mark.parametrize("ctype", ["text/plain", "application/x-www-form-urlencoded", "multipart/form-data; boundary=x", None])
def test_a_same_origin_upload_of_another_type_is_refused(client, journal_dir, ctype):
    headers = HEADER | SAME_ORIGIN | ({"Content-Type": ctype} if ctype else {})
    r = client.post("/api/journal/upload?name=trades.csv", content=b"a,b\n1,2\n", headers=headers)
    assert r.status_code == 415, r.text
    assert "application/octet-stream" in r.json()["detail"]
    assert _files(journal_dir) == []


@pytest.mark.unit
@pytest.mark.parametrize(("ctype", "name"), [("application/octet-stream", "t.csv"), ("text/csv; charset=utf-8", "t.csv"), (XLSX, "t.xlsx")])
def test_an_allowed_type_is_saved(client, journal_dir, ctype, name):
    r = client.post(f"/api/journal/upload?name={name}", content=b"a,b\n1,2\n", headers=HEADER | SAME_ORIGIN | {"Content-Type": ctype})
    assert r.status_code == 200, r.text
    assert r.json() == {"name": name} and _files(journal_dir) == [name]
