"""L4 follow-up on POST /api/trades:
(a) a ValueError / KeyError / TypeError from the take path (e.g. trade_record's unknown strategy direction) is a 400
    "Not taken: <message>" again, not a 500;
(b) a missing, null or empty run_id is the old refusal, 400 "Not taken: This run is not on file: run the analysis
    again.", saved under My picks like any refused take, not a 422 list the page can't show."""

import pytest

from tests import test_audit_b_support as support
from tests.test_audit_b_support import HEADER
from webapp import trade_record as tr

client, loopback = support.client, support.loopback          # the shared fixtures

NOT_ON_FILE = "This run is not on file: run the analysis again."


@pytest.fixture
def record(monkeypatch):
    seen = {"take": [], "refused": []}

    def take(run_id, candidate, confirm=False):
        seen["take"].append(run_id)
        if not run_id:
            raise tr.TradeError(NOT_ON_FILE)
        return {"id": "t1"}

    monkeypatch.setattr(tr, "take_from_run", take)
    monkeypatch.setattr(tr, "record_refused", lambda run_id, candidate, exc, who: seen["refused"].append((run_id, candidate, str(exc), who)))
    return seen


@pytest.mark.unit
@pytest.mark.parametrize("error", [ValueError("Unknown strategy direction: sideways"), KeyError("legs"), TypeError("bad leg")])
def test_a_plain_error_in_the_take_path_is_not_taken_400(client, record, monkeypatch, error):
    def fail(*a, **k):
        raise error

    monkeypatch.setattr(tr, "take_from_run", fail)
    r = client.post("/api/trades", json={"run_id": "r1", "candidate": 0}, headers=HEADER)
    assert r.status_code == 400, r.text
    assert r.json() == {"detail": f"Not taken: {error}"}


@pytest.mark.unit
@pytest.mark.parametrize("body", [{"candidate": 0}, {"run_id": None, "candidate": 0}, {"run_id": "", "candidate": 0}])
def test_a_missing_run_id_is_the_not_on_file_refusal_and_it_is_saved(client, record, body):
    r = client.post("/api/trades", json=body, headers=HEADER)
    assert r.status_code == 400, r.text
    assert r.json() == {"detail": f"Not taken: {NOT_ON_FILE}"}
    assert record["take"] == [""] and record["refused"] == [("", 0, NOT_ON_FILE, "you")]
