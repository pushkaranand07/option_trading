# Market Map

> **Status:** Current.
> **Scope:** `scripts/market_map.py`, `scripts/market_map_template.html`, `docs/data/market_events_2021_2026.json`;
> output `reports/market_map/` (gitignored).
> **Last verified against the code:** 2026-10-24

---

## 1. What it is

One HTML page that places every researched regulatory change and market event since January 2021 on the market it
moved, with each impact **measured from NSE's own daily files**, not taken from headlines. It is rebuilt by the daily
job (step 6, [15](15-daily-refresh-and-paper-trading.md)). User guide: [../features/market-map.md](../features/market-map.md).

## 2. Inputs

| Input | Source |
|---|---|
| NIFTY, BANKNIFTY, India VIX closes and stock closes | `prices/prices.parquet` (NSE index bars, [11](11-nse-data-store.md)) |
| Options contracts, options value traded, put-call ratio (OI), lot size, futures OI for NIFTY and BANKNIFTY | `fo_summary` |
| FII / Client / Pro / DII share of index-futures longs | `participant` (`fut_idx_long / (fut_idx_long + fut_idx_short)`) |
| Regime label | `regime/regime.parquet` |
| Researched events | `docs/data/market_events_2021_2026.json` |

The series start at a warm-up date of 2020-09-01 so the first 2021 events have a "before" window; the page shows
2021-01-01 onward.

## 3. Events

**Researched events file.** `docs/data/market_events_2021_2026.json` is a list of objects with `date`, `title`,
`category`, `detail`, `kind` (`regulatory` or `news`), `source` (an official circular or news link) and optionally
`source2`. As of this commit it holds 99 entries: 54 `regulatory` and 45 `news`, in the categories F&O structure,
macro, global, policy, geopolitical, settlement, margin, market, tax, corporate, election and charges. It is public,
sourced reference data and is committed ([../development/data-and-secrets.md](../development/data-and-secrets.md)).
`--events <file>` points the script at another file.

**Detected events** (`detected_events`), found in the data itself:

- the 8 largest NIFTY falls and the 5 largest rises (log return of the official close);
- every NIFTY and BANKNIFTY lot-size change in the F&O bhavcopy.

A detected big day whose session is already explained by a researched event is dropped, so it is shown once, as that
event.

## 4. Impact windows — `impact(df, date)`

Measured around the **first trading session on or after** the event date (an event needs at least 21 earlier
sessions):

| Field | Window |
|---|---|
| `nifty_day`, `nifty_5d`, `nifty_20d` | NIFTY return from the previous close over 1, 5 and 20 sessions |
| `vix_before`, `vix_after5` | India VIX the session before, and 5 sessions later |
| `rv_before`, `rv_after` | NIFTY realised vol over the 20 sessions before and after |
| `opt_before` / `opt_after`, `bn_opt_before` / `bn_opt_after` | Mean **notional options value traded** (₹) for NIFTY and BANKNIFTY, 20 sessions before vs after |
| `pcr_before` / `pcr_after` | NIFTY put-call ratio (OI), 5 sessions before vs after |
| `fii_before` / `fii_after` | FII share of index-futures longs, 5 sessions before vs after |
| `regime` | Regime label on the session |

Options activity is measured by **value traded, not contract count**: lot-size changes make contract counts jump
without any change in activity.

## 5. Network

`network()` correlates daily moves of the 29 stocks, NIFTY, BANKNIFTY, India VIX (log change) and FII positioning
(change in the long share) in three periods: 2021-22, 2023-24 and 2025-26. A link joins any pair with |correlation| ≥
0.45; each period also lists every node's correlation with NIFTY. Nodes are grouped by sector (`universe.SECTOR_OF`),
index, volatility and flows.

## 6. The page

`render()` embeds the data as JSON in `scripts/market_map_template.html` (replacing `/*__DATA__*/`), so the page opens
straight from disk. Sections:

1. **Timeline** — NIFTY with regime shading and event ticks coloured by type; hover for a day's numbers.
2. **Impact map** — each event at (NIFTY move on its first session, change in India VIX over 5 sessions), sized by the
   change in NIFTY options value traded; a median table by event type and the typical day's move.
3. **Event → impact ledger** — every event with its measured changes, filterable by type.
4. **Market network** — the correlation network per period (drag nodes to rearrange).
5. **How this page is built** — sources, and the update log.

`--note "text"` adds a timestamped line to `reports/market_map/log.json`, shown in the last section.

The page loads D3 7.8.5 from cdnjs and fonts from Google Fonts.

## 7. Outputs

`reports/market_map/india-market-map.html` and `reports/market_map/log.json`. The folder is gitignored because the page
embeds NSE data. The script prints the number of sessions, events and network links.

## 8. Findings recorded (tracker, 2026-10-24)

- Elections moved NIFTY most (median 2.7% on the day), geopolitics 2.1%, tax and margin rules about 0.2% (typical day
  0.5%).
- When BANKNIFTY weekly options ended (Nov-2024), NIFTY options value rose 33–43% and BANKNIFTY's fell 52–70%.
- News figures were cross-checked against NSE closes: 19/22 exact; 1 date fixed, 1 intraday figure removed.
- The cross-check exposed the weekend-session bug ([11](11-nse-data-store.md), section 3); after the fix the Sunday
  2026-02-01 Budget session is measured on its own: −1.96%.

These figures come from the page as built on 2026-10-24; the daily rebuild adds new sessions.
