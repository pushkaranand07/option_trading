"""Lot sizes and expiries from data (P-08) and point-in-time index membership (P-09)."""

import io
import zipfile
from datetime import date, datetime

import pandas as pd
import pytest

from tradingagents.dataflows.errors import NoMarketDataError
from tradingagents.dataflows.vendors.nse.client import Fetched, NSEDataNotPublishedError
from tradingagents.dataflows.vendors.nse.derivatives import (
    LotSizeHistory,
    derive_legacy_lot_sizes,
    describe_expiries,
    expiries_from_bhavcopy,
    fno_symbol,
    fo_bhavcopy,
    legacy_url,
    normalize_legacy,
    normalize_udiff,
    udiff_url,
)
from tradingagents.dataflows.vendors.nse.indices import ConstituentStore, survivorship_warning


def udiff_rows(day="2026-10-21", lot=65):
    """Real UDiFF column layout; values trimmed from the 21-Oct-2026 file."""
    base = {"TradDt": day, "BizDt": day, "Sgmt": "FO", "Src": "NSE", "FinInstrmId": 1, "ISIN": None,
            "SctySrs": None, "FininstrmActlXpryDt": None, "FinInstrmNm": "x", "LastPric": 0,
            "PrvsClsgPric": 0, "TtlNbOfTxsExctd": 1, "SsnId": "F1", "Rmks": None,
            "Rsvd1": None, "Rsvd2": None, "Rsvd3": None, "Rsvd4": None}
    rows = [
        dict(base, FinInstrmTp="IDO", TckrSymb="NIFTY", XpryDt="2026-10-27", StrkPric=23500.0, OptnTp="PE",
             OpnPric=520.25, HghPric=845.6, LwPric=407.05, ClsPric=773.45, UndrlygPric=22811.35, SttlmPric=773.45,
             OpnIntrst=5009030, ChngInOpnIntrst=-242905, TtlTradgVol=50724, TtlTrfVal=79493519254.5, NewBrdLotQty=lot),
        dict(base, FinInstrmTp="IDO", TckrSymb="NIFTY", XpryDt="2026-11-09", StrkPric=22800.0, OptnTp="CE",
             OpnPric=300, HghPric=320, LwPric=250, ClsPric=280, UndrlygPric=22811.35, SttlmPric=280,
             OpnIntrst=10, ChngInOpnIntrst=1, TtlTradgVol=5, TtlTrfVal=1.0, NewBrdLotQty=lot),
        dict(base, FinInstrmTp="IDF", TckrSymb="NIFTY", XpryDt="2026-10-27", StrkPric=None, OptnTp=None,
             OpnPric=22800, HghPric=22900, LwPric=22700, ClsPric=22850, UndrlygPric=22811.35, SttlmPric=22850,
             OpnIntrst=100, ChngInOpnIntrst=1, TtlTradgVol=1000, TtlTrfVal=1.0, NewBrdLotQty=lot),
    ]
    return pd.DataFrame(rows)


def legacy_rows():
    """Real legacy layout, 01-Jan-2024 (NIFTY lot 50, BANKNIFTY lot 15)."""
    return pd.DataFrame([
        {"INSTRUMENT": "FUTIDX", "SYMBOL": "NIFTY", "EXPIRY_DT": "25-Jan-2024", "STRIKE_PR": 0.0, "OPTION_TYP": "XX",
         "OPEN": 21800, "HIGH": 21850, "LOW": 21700, "CLOSE": 21800.0, "SETTLE_PR": 21800.0, "CONTRACTS": 100000,
         "VAL_INLAKH": 100000 * 50 * 21790 / 1e5, "OPEN_INT": 1, "CHG_IN_OI": 0, "TIMESTAMP": "01-JAN-2024"},
        {"INSTRUMENT": "FUTIDX", "SYMBOL": "BANKNIFTY", "EXPIRY_DT": "25-Jan-2024", "STRIKE_PR": 0.0, "OPTION_TYP": "XX",
         "OPEN": 48580.0, "HIGH": 48869.0, "LOW": 48389.4, "CLOSE": 48535.7, "SETTLE_PR": 48535.7, "CONTRACTS": 120422,
         "VAL_INLAKH": 878243.28, "OPEN_INT": 2052195, "CHG_IN_OI": -25530, "TIMESTAMP": "01-JAN-2024"},
        {"INSTRUMENT": "OPTIDX", "SYMBOL": "NIFTY", "EXPIRY_DT": "04-Jan-2024", "STRIKE_PR": 21800.0, "OPTION_TYP": "CE",
         "OPEN": 100, "HIGH": 120, "LOW": 90, "CLOSE": 110, "SETTLE_PR": 110, "CONTRACTS": 10, "VAL_INLAKH": 1.0,
         "OPEN_INT": 5, "CHG_IN_OI": 1, "TIMESTAMP": "01-JAN-2024"},
    ])


@pytest.mark.unit
def test_both_bhavcopy_formats_normalize_to_one_schema():
    new, old = normalize_udiff(udiff_rows()), normalize_legacy(legacy_rows())
    assert list(new.columns) == list(old.columns)
    assert new.loc[0, "option_type"] == "PE" and new.loc[0, "instrument"] == "OPTIDX"
    assert pd.isna(new.loc[2, "option_type"])
    assert old.loc[2, "expiry"] == date(2024, 1, 4)


@pytest.mark.unit
def test_legacy_lot_size_is_derived_from_turnover():
    assert derive_legacy_lot_sizes(normalize_legacy(legacy_rows())) == {"NIFTY": 50, "BANKNIFTY": 15}


@pytest.mark.unit
def test_lot_history_answers_by_date_and_admits_uncertainty(tmp_path):
    h = LotSizeHistory(tmp_path / "lots.json")
    h.update_from_bhavcopy(normalize_legacy(legacy_rows()))          # 2024-01-01: 50 (derived)
    h.record("NIFTY", date(2024, 3, 1), 50)
    h.update_from_bhavcopy(normalize_udiff(udiff_rows(lot=65)))      # 2026-10-21: 65 (exact)
    h.save()
    h = LotSizeHistory(tmp_path / "lots.json")                       # survives a reload

    assert h.lot_size("NIFTY", date(2024, 2, 1)).lot_size == 50      # inside the 50 run
    assert h.lot_size("NIFTY", date(2026, 10, 21)).confidence == "observed"
    with pytest.raises(NoMarketDataError, match="lot changed from 50 to 65"):
        h.lot_size("NIFTY", date(2025, 6, 1))                        # between runs that differ
    with pytest.raises(NoMarketDataError, match="before the first observed"):
        h.lot_size("NIFTY", date(2023, 1, 1))
    assert h.lot_size("NIFTY", date(2026, 11, 5)).confidence == "extrapolated"
    with pytest.raises(NoMarketDataError, match="refresh"):
        h.lot_size("NIFTY", date(2027, 6, 1))


@pytest.mark.unit
def test_expiries_come_from_traded_contracts_with_their_real_weekdays():
    expiries = expiries_from_bhavcopy(normalize_udiff(udiff_rows()), "NIFTY")
    assert expiries == [date(2026, 10, 27), date(2026, 11, 9)]
    assert describe_expiries(expiries) == "27-Oct-2026 (Tue), 09-Nov-2026 (Mon)"   # holiday-shifted Monday


@pytest.mark.unit
def test_fno_symbol_mapping():
    assert fno_symbol("^NSEI") == "NIFTY" and fno_symbol("^NSEBANK") == "BANKNIFTY"
    assert fno_symbol("reliance.ns") == "RELIANCE"


def _zip(df):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("bhav.csv", df.to_csv(index=False))
    return buf.getvalue()


class ArchiveClient:
    def __init__(self, files):
        self.files, self.asked = files, []

    def get_archive(self, url, ttl=None):
        self.asked.append(url)
        if url not in self.files:
            raise NSEDataNotPublishedError(url)
        return Fetched(self.files[url], url, datetime.now())


@pytest.mark.unit
def test_fo_bhavcopy_picks_the_format_for_the_date_and_falls_back():
    day = date(2026, 10, 21)
    client = ArchiveClient({udiff_url(day): _zip(udiff_rows())})
    assert fo_bhavcopy(day, client)["format"].iloc[0] == "udiff"

    old_day = date(2024, 1, 1)
    client = ArchiveClient({legacy_url(old_day): _zip(legacy_rows())})
    assert fo_bhavcopy(old_day, client)["format"].iloc[0] == "legacy"
    assert client.asked[0] == legacy_url(old_day)                    # legacy tried first for old dates

    with pytest.raises(NoMarketDataError, match="holiday or not yet published"):
        fo_bhavcopy(date(2026, 10, 20), ArchiveClient({}))


# ---------------------------------------------------------------- universe


def store_with_history(tmp_path):
    s = ConstituentStore(tmp_path)
    s.record_snapshot("NIFTY 50", date(2026, 10, 22), ["A", "B", "NEW"])
    s.add_change("NIFTY 50", date(2026, 9, 30), added=["NEW"], removed=["OLD"])
    return s


@pytest.mark.unit
def test_membership_before_a_change_is_reconstructed(tmp_path):
    s = store_with_history(tmp_path)
    s.set_complete_since("NIFTY 50", date(2026, 1, 1))
    m = s.members_as_of("^NSEI", date(2026, 9, 1))
    assert m.symbols == ("A", "B", "OLD") and m.method == "reconstructed" and m.survivorship_safe
    assert s.members_as_of("NIFTY 50", date(2026, 10, 1)).symbols == ("A", "B", "NEW")


@pytest.mark.unit
def test_membership_beyond_the_change_log_is_flagged_as_biased(tmp_path):
    s = store_with_history(tmp_path)      # change log not declared complete
    m = s.members_as_of("NIFTY 50", date(2020, 1, 1))
    assert not m.survivorship_safe
    assert "SURVIVORSHIP WARNING" in survivorship_warning(m)


@pytest.mark.unit
def test_snapshot_dates_are_exact(tmp_path):
    s = store_with_history(tmp_path)
    m = s.members_as_of("NIFTY 50", date(2026, 10, 22))
    assert m.method == "snapshot" and m.survivorship_safe and survivorship_warning(m) == ""
    assert m.yahoo_tickers() == ["A.NS", "B.NS", "NEW.NS"]


@pytest.mark.unit
def test_no_snapshot_is_an_explicit_error(tmp_path):
    with pytest.raises(NoMarketDataError, match="refresh"):
        ConstituentStore(tmp_path).members_as_of("NIFTY 50", date(2026, 1, 1))
