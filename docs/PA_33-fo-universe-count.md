# PA-33 — Data foundation step 2, part 1: count of the whole F&O universe (nothing ingested)

| | |
|---|---|
| **Status** | Done (count only). Ingest waits for the user's filter choice |
| **Scope** | new `scripts/quant_count_fo_universe.py`, `scripts/quant_count_fo_summary.py`; `docs/data_catalog.md` (stale Chronos outputs); `tests/test_research_import_guard.py` (allow-list entry) |
| **Related** | [PA-31](PA_31-research-splits-and-locked-loader.md), [PA-32](PA_32-prices-holiday-bars.md), [data catalog](data_catalog.md), [architecture/11](architecture/11-nse-data-store.md) |
| **Pull request** | branch `data/step-2-fo-count` |
| **Date** | 2026-10-27 |

Research and decision support only, not investment advice.

## 1. Problem

Removing survivorship bias means storing every F&O underlying that ever traded since 2010, not today's 29 survivors.
The user asked for the size of that first, measured where possible, with any extrapolated figure marked ESTIMATE, and
2–3 filter options with row counts and disk sizes, so they can choose before anything is ingested.

## 2. Method

- **2015 to 2026-10-26: every raw F&O bhavcopy already on disk (2,926 files), parsed in full** with the store's own
  parser (`datastore.parse_fo`). The reference price for moneyness is the store's: NSE's underlying price, else the
  near-month future close.
- **2010–2014: a sample of 60 real NSE files**, the first available F&O bhavcopy of each month (12 per year),
  downloaded to a scratch folder, not into the store. Row counts for those years are **ESTIMATE** = mean rows per
  sampled file × estimated sessions (weekdays minus NSE's F&O holidays for the year; NSE's API lists no 2010 holidays,
  so 2010's 261 counts every weekday and is high).
- **The sampling method, tested on 2015–2019 where every file exists:** it **under**states rows under the current
  filter by 11.4–15.2% and all rows by 1.7–3.8%, and finds every underlying of the year but one (2016: 189 of 190).
  The 2010–2014 estimates below are not adjusted for this.
- **Disk for derived tables: ESTIMATE** = rows × 16.29 bytes per row, what the current option chain uses
  (251,315,286 bytes for 15,429,717 rows).
- **Delisted / renamed:** NSE's `symbolchange.csv` and `EQUITY_L.csv` (current equity list), fetched 2026-10-27.

## 3. Results

### Underlyings

| Year | Files | Index | Stock | Basis |
|---|---|---|---|---|
| 2010 | 12 | 5 | 230 | sample (lower bound) |
| 2011 | 12 | 9 | 241 | sample |
| 2012 | 12 | 10 | 230 | sample |
| 2013 | 12 | 10 | 155 | sample |
| 2014 | 12 | 9 | 148 | sample |
| 2015 | 248 | 13 | 166 | measured |
| 2016 | 247 | 10 | 179 | measured |
| 2017 | 248 | 10 | 218 | measured |
| 2018 | 246 | 8 | 211 | measured |
| 2019 | 245 | 3 | 202 | measured |
| 2020 | 252 | 3 | 153 | measured |
| 2021 | 247 | 3 | 197 | measured |
| 2022 | 248 | 4 | 203 | measured |
| 2023 | 246 | 4 | 192 | measured |
| 2024 | 249 | 5 | 231 | measured |
| 2025 | 249 | 5 | 258 | measured |
| 2026 | 201 | 6 | 226 | measured |

**Ever, 2010 to today: 19 index symbols, 473 stock symbols, 1 other (INDIAVIX futures).** These are distinct
*symbols*: a renamed company counts once per symbol. Index symbols: BANKNIFTY, CNXINFRA, CNXIT, CNXPSE, DJIA,
FINNIFTY, FTSE100, MIDCPNIFTY, MINIFTY, NFTYMCAP50, NIFTY, NIFTYCPSE, NIFTYFPI, NIFTYINFRA, NIFTYIT, NIFTYMID50,
NIFTYNXT50, NIFTYPSE, S&P500.

### Names that left F&O before 2026-10-26: 274

| Status | Count |
|---|---|
| Stock, still on NSE's equity list (left F&O only) | 135 |
| Stock, renamed (NSE symbol-change list) | 57 |
| Stock, not on NSE's current equity list and no symbol change recorded: delisted or merged, **reason UNVERIFIED** | 68 |
| Index or other, no longer in F&O | 14 |

**Renamed (57):** JPHYDRO→JPPOWER, WELGUJ→WELCORP, TATATEA→TATAGLOBAL, NAGARCONST→NCC, INFOSYSTCH→INFY,
ISPATIND→JSWISPAT, HEROHONDA→HEROMOTOCO, COREPROTEC→COREEDUTEC, MLL→MERCATOR, MUNDRAPORT→ADANIPORTS,
JINDALSWHL→JSWHL, HOTELEELA→HLVLTD, NEYVELILIG→NLCINDIA, AREVAT&D→ALSTOMT&D, ALSTOMT&D→GET&D, APIL→AIL,
INDIAINFO→IIFL, AIL→GEPIL, ORCHIDCHEM→ORCHIDPHAR, PIRHEALTH→PEL, MAX→MFSL, DCB→DCBBANK, STRTECH→STLTECH,
GUJFLUORO→GFLLIMITED, BHUSANSTL→TATASTLBSL, PANTALOONR→FRL, SESAGOA→SSLT, FINANTECH→63MOONS, UNIPHOS→UPL, FRL→FEL,
SSLT→VEDL, SKSMICRO→BHARATFIN, CROMPGREAV→CGPOWER, RDEL→RNAVAL, IBREALEST→EMBDL, IDFCBANK→IDFCFIRSTB, KPIT→BSOFT,
INFIBEAM→CCAVENUE, TATAGLOBAL→TATACONSUM, NIITTECH→COFORGE, CENTURYTEX→ABREL, INFRATEL→INDUSTOWER,
CADILAHC→ZYDUSLIFE, MOTHERSUMI→MOTHERSON, LTI→LTIM, SRTRANSFIN→SHRIRAMFIN, AMARAJABAT→ARE&M, PVR→PVRINOX,
IBULHSGFIN→SAMMAANCAP, L&TFH→LTF, MCDOWELL-N→UNITDSPR, GMRINFRA→GMRAIRPORT, GUJGASLTD→GUJENERGY, ZOMATO→ETERNAL,
TATAMOTORS→TMPV, LTIM→LTM, ICICIPRULI→ICICILIFE.

**Not on NSE's current equity list, no symbol change recorded (68):** SAMRUDDHI, ICSA, RNRL, STERLINBIO, TV-18,
ORBITCORP, RELMEDIA, NAGARFERT, MOSERBAER, KFA, KSOILS, GITANJALI, GTOFFSHORE, 3IINFOTECH, TULIP, DCHL, MERCATOR,
PATNI, ABGSHIP, BRFL, NAGAROIL, TATACOFFEE, EDUCOMP, ESSAROIL, ROLTA, RUCHISOYA, VIDEOIND, POLARIS, SKUMARSYNF,
COREEDUTEC, JSWISPAT, LITL, ALOKTEXT, IVRCLINFRA, STER, PUNJLLOYD, OPTOCIRCUI, VIJAYABANK, DENABANK, GSKCONS, RANBAXY,
AMTEKAUTO, CAIRN, ABIRLANUVO, SINTEX, RNAVAL, ANDHRABANK, DALMIABHA, CAPF, SREINFRA, JPASSOCIAT, ALBK, SYNDIBANK,
JETAIRWAYS, ORIENTBANK, TV18BRDCST, BHARATFIN, DHFL, RELCAPITAL, HEXAWARE, TATAMTRDVR, UJJIVAN, EQUITAS, MINDTREE,
GSPL, HDFC, IDFC, PEL. Some are mergers (e.g. HDFC, MINDTREE, the merged public-sector banks), some failures; this
list does not say which. The full table with first and last F&O dates is `reports/fo_count/left_fo.csv` (gitignored).

### Option rows and disk, by filter option

Rows in millions. 2015–2026 MEASURED, 2010–2014 ESTIMATE (method above: likely 11–15% low for the filtered options).

| Option | 2010–14 (ESTIMATE) | 2015–26 (MEASURED) | Total | Disk (ESTIMATE) |
|---|---|---|---|---|
| A. All underlyings, ±25% moneyness, ≤70 days (the current filter) | 13.2 | 80.2 | **93.4M** | ~1.52 GB |
| B. All underlyings, ±10%, ≤35 days | 2.9 | 22.6 | **25.5M** | ~0.42 GB |
| C. Top 100 by F&O turnover each year, ±25%, ≤70 days | 7.4 | 46.5 | **53.9M** | ~0.88 GB |
| D. Top 50 by F&O turnover each year, ±15%, ≤35 days | 1.3 | 12.1 | **13.4M** | ~0.22 GB |
| Unfiltered: every option row, every underlying | 33.7 | 122.9 | **156.5M** | ~2.55 GB |
| *For reference: today's store (31 symbols, 2018–2026, filter A)* | — | 15.4 | 15.4M | 0.25 GB (measured) |

Per year (millions of rows):

| Year | Basis | A | B | C | D | Unfiltered |
|---|---|---|---|---|---|---|
| 2010 | ESTIMATE | 2.70 | 0.61 | 1.41 | 0.26 | 6.47 |
| 2011 | ESTIMATE | 2.64 | 0.55 | 1.19 | 0.21 | 7.79 |
| 2012 | ESTIMATE | 2.36 | 0.52 | 1.23 | 0.21 | 6.85 |
| 2013 | ESTIMATE | 2.52 | 0.56 | 1.67 | 0.28 | 6.27 |
| 2014 | ESTIMATE | 2.94 | 0.69 | 1.93 | 0.35 | 6.27 |
| 2015 | MEASURED | 3.96 | 0.96 | 2.59 | 0.48 | 7.36 |
| 2016 | MEASURED | 4.67 | 1.15 | 2.59 | 0.51 | 8.47 |
| 2017 | MEASURED | 5.89 | 1.54 | 2.85 | 0.59 | 10.00 |
| 2018 | MEASURED | 5.51 | 1.37 | 2.76 | 0.59 | 10.15 |
| 2019 | MEASURED | 5.49 | 1.41 | 3.41 | 0.80 | 9.32 |
| 2020 | MEASURED | 5.05 | 1.23 | 3.80 | 0.87 | 9.05 |
| 2021 | MEASURED | 8.18 | 1.99 | 5.39 | 1.31 | 13.49 |
| 2022 | MEASURED | 9.58 | 2.33 | 5.34 | 1.34 | 15.86 |
| 2023 | MEASURED | 9.70 | 2.90 | 5.68 | 1.67 | 12.67 |
| 2024 | MEASURED | 8.19 | 2.95 | 4.92 | 1.74 | 9.84 |
| 2025 | MEASURED | 7.24 | 2.51 | 3.71 | 1.14 | 8.61 |
| 2026 | MEASURED | 6.72 | 2.29 | 3.44 | 1.03 | 8.04 |

### Raw disk

- 2015–2026 F&O files on disk: **MEASURED 1.91 GB** (83 MB in 2015 rising to 280 MB in 2025). All raw kinds together: 2.14 GB.
- 2010–2014 F&O files not yet downloaded: **ESTIMATE ~348 MB** (sampled mean file size × estimated sessions: 66, 78,
  70, 66 and 68 MB).

### Lot sizes and expiry calendar

| Years | Lot size | Expiry dates |
|---|---|---|
| 2024-07-08 onward (UDiFF format) | **Stated in the file** (100% of day-underlyings in 2025–26) | Listed in the files |
| 2018 to 2024-07 (legacy) | Derived from open interest (98.5–100% derivable). The store already uses this and the tracker records it as exact | Listed in the files |
| 2015–2017 (legacy, raw on disk) | Derivable for 97.9–98.5% of day-underlyings; **not cross-checked: needs NSE circulars** to confirm | Listed in the files |
| 2010–2014 (sample only) | Derivable for 98.2–99.8% in the sample; **needs the files and NSE circulars** | Monthly expiries visible in the sample (12–13 a year); the full list needs the files |

Distinct option expiry dates listed in the files, by year of expiry (MEASURED from 2015; sample before):
NIFTY 12 a year until 2018, then 47–55 (weekly options from 2019); BANKNIFTY 12 until 2015, 36 in 2016, 52–58 in
2017–2024, 20 in 2025 and 14 in 2026 (weekly options ended in November 2024); stocks 12–13 every year. The reason for
the counts above 52 (e.g. 58 in 2023, 55 in 2025) is not checked here: they are counted as listed.

**What needs NSE circulars:** the 2010–2014 trading calendar (the holiday API gives none for 2010 and an incomplete
2011), and a check of derived lot sizes before 2018. Expiry dates themselves come from the files for every year whose
files are downloaded.

## 4. Decisions

None yet. Waiting for the user's filter choice; no filter is recommended here (user).

## 5. Tests

`tests/test_research_import_guard.py` lists `scripts/quant_count_fo_universe.py` (it reads raw files and writes only
to `reports/fo_count/`). No other code changed.

## 6. Verification

The sampling method was checked against 2015–2019's complete files (§2). Counts are reproducible:

```powershell
.venv\Scripts\python.exe scripts\quant_count_fo_universe.py --sample-dir <folder with the 60 sample files>
.venv\Scripts\python.exe scripts\quant_count_fo_summary.py --nse-lists <folder> --holidays <holiday JSON> --bytes-per-row 16.29
```

## 7. Risks and open items

- 2010–2014 figures are a sample: counts of names are lower bounds, row counts ESTIMATE and probably low.
- "Not on NSE's current equity list" mixes delistings, mergers and suspensions; the reason per name is UNVERIFIED.
- Disk figures assume the current table's compression holds for every underlying: ESTIMATE.
- Not ingested: anything. The 60 sample files are in a scratch folder, not in the store.
