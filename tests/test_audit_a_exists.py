"""Audit follow-up (A-exists): ``STORE.exists()`` sat outside the try in ``_load``; on Python 3.13 ``Path.exists`` can
raise PermissionError (a folder the account may not list). That escaped as a raw OSError: the page crashed and the
writers raised something that is not a TradeError. Now it is StoreCorrupt (no backup copy for an OSError), and
overview() still returns a view that says why."""

import pytest

from tests.test_trade_record import RESULT
from webapp import trade_record as tr


@pytest.fixture
def denied(tmp_path, monkeypatch):
    class Denied(type(tmp_path)):
        def exists(self, *a, **k):
            raise PermissionError(13, "Access is denied", str(self))

    monkeypatch.setattr(tr, "STORE", Denied(tmp_path / "trades.json"))
    monkeypatch.setattr(tr, "_market_open", lambda *a: True)
    return tmp_path


@pytest.mark.unit
def test_an_exists_permission_error_is_a_store_problem_not_a_crash(denied):
    o = tr.overview(lambda *a: {"spot": 0, "rows": []})
    assert o["open"] == [] and "Access is denied" in o["store_problem"]
    with pytest.raises(tr.StoreCorrupt):
        tr.take(RESULT)
    assert "Access is denied" in tr.store_problem()
    assert not list(denied.glob("trades.json.corrupt-*"))           # no backup for an OSError
    assert tr.history_csv().splitlines()[1].startswith("store problem,")
