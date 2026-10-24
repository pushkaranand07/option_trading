# Market Map

> **Status:** Current.
> **Scope:** the India Market Map 2021–26 page.
> **Last verified against the code:** 2026-10-24

---

## 1. What it does for you

Shows what each law change and market event since January 2021 actually did to the market, measured from NSE's own
daily files: NIFTY's move on the day and over 5 and 20 sessions, India VIX, realised volatility, options value traded,
put-call ratio and FII positioning before vs after. It also shows how stocks, indices, VIX and FII positioning move
together in 2021-22, 2023-24 and 2025-26.

Findings recorded on 2026-10-24: elections moved NIFTY most (median 2.7% on the day), geopolitics 2.1%, tax and margin
rules about 0.2% (typical day 0.5%); when BANKNIFTY weekly options ended (Nov-2024) NIFTY options value rose 33–43% and
BANKNIFTY's fell 52–70%.

## 2. How to use it

The daily refresh rebuilds it. Open `reports\market_map\india-market-map.html` in a browser. Hover the timeline for a
day's numbers; click an event tick or dot to open it in the ledger; filter the ledger by type; switch the network
period and drag nodes.

To rebuild by hand (needs the built store and regime file):

```powershell
.venv\Scripts\python.exe scripts\market_map.py
.venv\Scripts\python.exe scripts\market_map.py --note "added the 2026 SEBI circular"   # also logs the change on the page
```

To add a researched event, add an object to `docs/data/market_events_2021_2026.json` with `date`, `title`, `category`,
`detail`, `kind` (`regulatory` or `news`) and `source` (official or news link), then rebuild.

## 3. Files

`scripts/market_map.py`, `scripts/market_map_template.html`, `docs/data/market_events_2021_2026.json`.

## 4. Settings

`--out <folder>` (default `reports/market_map`), `--events <file>`, `--note <text>`.

## 5. Outputs

`reports/market_map/india-market-map.html` and `reports/market_map/log.json` — gitignored, because the page embeds NSE
data. Do not commit or publish them.

## 6. Known issues

- The page loads D3 from cdnjs and fonts from Google Fonts, so charts need an internet connection to draw.
- Impacts are measured from the first session on or after the event date; an event published after the close shows
  its effect a day late.
- The events file (`docs/data/market_events_2021_2026.json`) holds 99 entries: 54 regulatory changes and 45 market
  events. 53 market events were researched; 8 describe the same day as an RBI or Budget row and are merged into it as
  its "market reaction" (`source2`). With the data-detected events the page lists 112.

How it is built: [../architecture/17-market-map.md](../architecture/17-market-map.md).
