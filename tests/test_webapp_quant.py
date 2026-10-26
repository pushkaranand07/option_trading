"""Web app tabs: risk, measured spreads, research results, and the trade journal (upload safety)."""

import json
from datetime import date

import pytest

from tradingagents.analytics import trial_log
from webapp import quant


def chain_json(stamp="23-Oct-2026 15:40:00", spot=100.0):
    def leg(k, bid, ask):
        return {"buyPrice1": bid, "sellPrice1": ask, "expiryDate": "24-11-2026", "strikePrice": k,
                "underlyingValue": spot, "impliedVolatility": 30}
    data = [{"strikePrice": k, "CE": leg(k, c - 0.2, c + 0.2), "PE": leg(k, p - 0.1, p + 0.1)}
            for k, c, p in ((95, 7.0, 2.0), (100, 4.0, 4.0), (105, 2.0, 7.0))]
    return {"records": {"timestamp": stamp, "underlyingValue": spot, "data": data}}


@pytest.mark.unit
def test_spreads_read_the_latest_snapshot_around_the_money(tmp_path):
    day = tmp_path / "option_quotes" / "2026-10-23"
    day.mkdir(parents=True)
    (day / "X_2026-11-24.json").write_text(json.dumps(chain_json()), encoding="utf-8")
    r = quant.spreads("x", root=tmp_path)
    assert r["available"] and r["snapshot"] == "2026-10-23"
    e = r["expiries"][0]
    assert e["atm"] == 100.0 and [row["strike"] for row in e["rows"]] == [95.0, 100.0, 105.0]
    atm = e["rows"][1]
    assert atm["ce"]["spread_pct"] == pytest.approx(0.4 / 4.0)
    assert quant.spreads("NOPE", root=tmp_path)["available"] is False


@pytest.mark.unit
def test_research_lists_tests_in_plain_words_and_reads_the_daily_status(tmp_path):
    log = tmp_path / "t.sqlite"
    trial_log.record(trial_log.Trial("results_iron_fly", {}, n_oos_trades=984, verdict="reject"), log)
    trial_log.record(trial_log.Trial("random", {}, n_oos_trades=10, gate_verdict="rejected"), log)
    status = tmp_path / "daily_status.json"
    status.write_text(json.dumps({"ok": True, "finished": "2026-10-23T21:01:54", "steps": []}), encoding="utf-8")
    r = quant.research(trial_path=log, status_file=status)
    assert [t["idea"] for t in r["tested"]] == ["results_iron_fly"]           # the random baseline is hidden
    t = r["tested"][0]
    assert t["name"] == "Sell options before company results" and t["verdict"] == "rejected" and not t["passed"]
    assert r["daily_job"]["ok"] and r["approved"] == [] and len(r["in_use"]) == 3


@pytest.mark.unit
def test_risk_outside_the_universe_says_so(tmp_path):
    r = quant.risk("AAPL", on=date(2026, 10, 23), root=tmp_path)
    assert r["in_universe"] is False and r["vol"] is None


@pytest.mark.unit
@pytest.mark.parametrize("name", ["../evil.csv", "..\\evil.xlsx", "C:/x/y.csv"])
def test_upload_names_are_reduced_to_a_plain_file_name(name):
    assert "/" not in quant.safe_name(name) and "\\" not in quant.safe_name(name)


@pytest.mark.unit
def test_uploads_must_be_tradebook_files_and_not_too_big(tmp_path, monkeypatch):
    monkeypatch.setattr(quant, "JOURNAL_DIR", tmp_path)
    with pytest.raises(ValueError, match="csv"):
        quant.save_upload("run.exe", b"x")
    with pytest.raises(ValueError, match="10 MB"):
        quant.save_upload("big.csv", b"x" * (quant.MAX_UPLOAD + 1))


@pytest.mark.unit
def test_journal_upload_and_analysis(tmp_path, monkeypatch):
    # The routes in webapp/server.py are thin wrappers (ValueError -> HTTP 400) around these functions.
    monkeypatch.setattr(quant, "JOURNAL_DIR", tmp_path)
    book = "\n".join(["Trade Date,Trade Time,Symbol,Buy/Sell,Quantity,Trade Price",
                      "06-10-2026,10:05:00,NIFTY 06 OCT 22600 CE,BUY,75,100",
                      "06-10-2026,11:00:00,NIFTY 06 OCT 22600 CE,SELL,75,120", ""])
    assert quant.save_upload("../../book.csv", book.encode()) == "book.csv" and (tmp_path / "book.csv").exists()
    assert [f["name"] for f in quant.journal_files()] == ["book.csv"]
    j = quant.journal("book.csv", horizon="intraday")
    assert j["round_trips"] == 1 and j["sections"]["Overall"][0]["trades"] == 1
    assert j["sections"]["By style"][0]["group"] == "option buying"
    with pytest.raises(ValueError, match="not in reports/journal"):
        quant.journal("missing.csv")


@pytest.mark.unit
def test_end_of_day_freshness_knows_the_latest_close_and_the_next_update():
    from datetime import date, datetime

    from tradingagents.dataflows.vendors.nse.calendar import NSECalendar
    from webapp import quant

    cal = NSECalendar({date(2026, 11, 10): "Diwali-Balipratipada"})
    monday_morning = quant.freshness("2026-10-23", datetime(2026, 10, 26, 11, 45), cal)     # Friday's close: current
    assert not monday_morning["stale"] and monday_morning["next_update"] == "today 7:30 PM"
    assert monday_morning["as_of_label"] == "Fri 23 Oct"
    missed = quant.freshness("2026-10-23", datetime(2026, 10, 26, 22, 30), cal)            # the nightly run missed Monday
    assert missed["stale"] and missed["expected"] == "2026-10-26" and missed["next_update"] == "Tue 27 Oct 7:30 PM"
    weekend = quant.freshness("2026-10-23", datetime(2026, 10, 25, 10, 0), cal)
    assert not weekend["stale"] and weekend["next_update"] == "Mon 26 Oct 7:30 PM" and not weekend["today_is_session"]
    holiday_eve = quant.freshness("2026-11-09", datetime(2026, 11, 9, 23, 0), cal)         # next run skips the holiday
    assert not holiday_eve["stale"] and holiday_eve["next_update"] == "Wed 11 Nov 7:30 PM"
    assert quant.freshness(None, datetime(2026, 10, 26, 12, 0), cal)["stale"]
