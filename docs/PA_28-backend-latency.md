# PA-28 — Backend latency: one fetch per key, refresh-ahead, stale-feed guard, measured p50 / p95 / p99

| | |
|---|---|
| **Status** | Done |
| **Scope** | `webapp/market_data.py` (`_TTLCache`, `start_refresh_ahead`, scrip-master parse, `bar_age` / `stale_bars`), `webapp/latency.py` (new), `webapp/server.py` (request timing, `GET /api/latency`, data age on candles), `webapp/planner.py` (stale-feed blockers), `webapp/option_chain.py` (NSE chain on the shared cache), `webapp/quant.py` (risk cached 60 s), `webapp/morning.py` (indices built in parallel), `tests/test_webapp_latency.py` |
| **Related** | [PA-02](PA_02-webapp.md), [PA-23](PA_23-ai-strategist-and-nse-option-chain.md), [PA-27](PA_27-pulse-trade-ranking.md) |
| **Pull request** | branch `feature/backend-latency` |
| **Date** | 2026-10-26 |

## 1. Problem

The user asked for the backend analysis to have no latency: fresh data, instantly, and never old prices shown as
current.

## 2. What was measured first

Measured on 2026-10-26. Live at 15:28 IST, then cold-profiled after the close.

- **Backend calculation is not the bottleneck.** A cached plan answers in 5–40 ms; calculation is 40–260 ms per path.
- **The waits come from fetching.** A request that found its cache expired waited on the source:
  - Yahoo candles: 0.15–1.1 s;
  - Yahoo quotes: ~0.3 s each, one after the other;
  - NSE chain: ~1 s cold, 0.8 s of it the cookie bootstrap.
- **Scrip master.** The first instrument lookup parsed Dhan's 216k-row scrip master with `csv.DictReader`: 2.55 s.
  It ran again every hour, on whichever request arrived then.
- **Risk.** Every call re-read the end-of-day parquet files: ~40–100 ms per request.
- **The feed itself.** `.env` has no Dhan token, so all prices are Yahoo / NSE website polls.
  - For 22 s, Yahoo NIFTY (22753.2) and NSE `allIndices` NIFTY (22717.05) were 36 points apart and neither moved.
  - Yahoo's `regularMarketTime` reads "now" even when the price has not moved, so it cannot prove freshness.

## 3. Change

### Cache: one fetch per key, refresh-ahead (`_TTLCache`)

- **One fetch per key.** Callers that miss together wait for one fetch instead of each calling Yahoo / NSE.
- **No older over newer.** A result never replaces one whose fetch started later.
- **Age.** A value's age is counted from when its fetch started and never exceeds its ttl. The ttls are unchanged:
  candles 4 s, daily 20 s, quotes 15 s, NSE chain 10 s, plan 10 s.
- **Refresh-ahead.** While the market is open, a background thread (`start_refresh_ahead`, started by the
  server) refetches keys read in the last 90 s before they expire.
  - Lead: 1 s or twice the key's last fetch time, at most 40% of the ttl.
  - At most 4 refetches at once.
  - A failed refetch backs off 30 s and leaves the last value in place.
  - Requests therefore read memory, and the sources are polled no faster than the ttls already allowed.
- **NSE chain and contract.** These moved from their own cache onto this one.

### Other speed-ups

- **Scrip master.** Lots and equities are parsed once per daily download and kept beside the file as JSON.
  Measured: 2.55 s → 2–8 ms.
- **Risk.** `quant.risk` is cached 60 s; its inputs change once a night.
- **Morning build.** `morning.build` builds the NIFTY and BANKNIFTY contexts in parallel.

### Stale data is never shown as current

- **Stale-bar rule.** While the market is open, a last 5-minute bar more than 10 minutes old (two bars) means the
  feed has stopped (`md.stale_bars`).
- **Plan blockers.** The plan is not safe, and says why, when:
  - its bars are stale, or
  - its prices are the saved copy (source `saved (...)`).
- **Data age in responses.**
  - `/api/plan`: `data: {last_bar_age_s, stale, built_at}`;
  - `/api/candles`: `data: {last_bar_age_s, stale, live}`.

### Measured latency (`GET /api/latency`)

- **Per API route:** p50 / p95 / p99 / max over the last 2,000 requests.
- **Per fetch kind:** for example `fetch c` (candles), `fetch nse chain`, `fetch plan`.

## 4. Results

Plan-tab traffic for 120 s against the `main` code and this branch, run back to back (same Yahoo conditions).

- **Traffic:** candles, quotes, plan, rank, risk and morning context, with a burst of 4 identical requests a
  quarter of the time.
- **Setup:** market-open behaviour forced on, since the run was after the close. Times are client-side, in ms.

| Endpoint | main p50 / p95 / p99 | branch p50 / p95 / p99 |
|---|---|---|
| candles NIFTY | 40 / 434 / 540 | 36 / 46 / 46 |
| quotes | 20 / 642 / 695 | 14 / 34 / 147 |
| plan BANKNIFTY | 20 / 932 / 1159 | 20 / 41 / 42 |
| rank | 231 / 1277 / 3750 | 74 / 117 / 139 |
| risk | 107 / 224 / 227 | 13 / 34 / 93 |
| morning context | 187 / 1225 / 1463 | 58 / 80 / 85 |
| **all requests** | **72 / 737 / 1277** | **28 / 95 / 139** |

The branch's maximum (2.8 s) is the first rank request after start: the NSE cookie bootstrap. The first request
after a restart dropped from ~2.0 s to ~1.3 s.

## 5. Not solved here: the feed itself

The backend now answers from memory in tens of milliseconds. The prices are still Yahoo / NSE website polls:

- Yahoo's bars arrive a few minutes late;
- NSE's chain updates about every 45 s (PA-23).

The only way to sub-second prices is a broker stream. The fit is Dhan's live market feed: the user trades on Dhan
and the code already speaks Dhan's REST API. It needs a Dhan Data API subscription and a daily access token. That
choice is the user's, and it is not made yet.

## 6. Tests

`tests/test_webapp_latency.py` (11):

- concurrent misses share one fetch;
- an older fetch cannot overwrite a newer one;
- no value is served older than its ttl;
- refresh-ahead refetches hot keys and leaves cold ones;
- a failing refresh backs off and keeps the last value;
- percentiles are correct;
- stale bars are detected only while the market is open;
- a plan on a stopped feed, or on saved bars, is blocked.

Full suite: 1665 passed, 6 skipped.
