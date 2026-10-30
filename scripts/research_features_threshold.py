"""Step 1 of the feature library: the IV liquidity threshold, from option-chain rows only (docs/PA_42).

    python scripts/research_features_threshold.py

European rows of 2015-2022. For each candidate on the thinner leg of a (date, symbol, expiry, strike) pair: the put-call
parity flag rate among tested pairs, and the share of rows kept. Reads no return and no target. Writes
reports/features/threshold.json.
"""

from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tradingagents.research import loader  # noqa: E402

CANDIDATES = (10, 25, 50, 100, 250, 500)
COLUMNS = ["trade_date", "symbol", "expiry", "strike", "option_type", "contracts", "parity_tested", "flag_parity", "exercise_style", "known_from"]
KEY = ["trade_date", "symbol", "expiry", "strike"]


def thinner_leg(chain: pd.DataFrame) -> pd.DataFrame:
    """One row per (date, symbol, expiry, strike) with both legs: the thinner leg's contracts, and the pair's parity flags."""
    c = chain[chain["option_type"] == "CE"].set_index(KEY)
    p = chain[chain["option_type"] == "PE"].set_index(KEY)
    out = c[["contracts", "parity_tested", "flag_parity"]].join(p[["contracts"]], rsuffix="_put", how="inner")
    out["thinner"] = np.minimum(out["contracts"], out["contracts_put"])
    return out.reset_index()


def table(tested: np.ndarray, flagged: np.ndarray, thinner: np.ndarray, european_rows: int) -> dict:
    out = {}
    for t in CANDIDATES:
        keep = thinner >= t
        n = int((keep & tested).sum())
        out[str(t)] = {"tested_pairs": n, "flagged": int((keep & flagged).sum()), "flag_rate": float((keep & flagged).sum() / n) if n else None,
                       "pairs_kept": int(keep.sum()), "rows_kept": int(2 * keep.sum()), "share_of_european_rows_kept": float(2 * keep.sum() / european_rows)}
    return out


def pick(result: dict, limit: float = 0.01) -> int | None:
    """The smallest candidate with a flag rate at or below ``limit``."""
    return next((t for t in CANDIDATES if result[str(t)]["flag_rate"] is not None and result[str(t)]["flag_rate"] <= limit), None)


def main() -> int:
    parts, rows = [], 0
    by_year = {}
    for year in range(2015, 2023):
        chain = loader.load("base_option_chain", start=date(year, 1, 1), end=date(year, 12, 31))[COLUMNS]
        chain = loader.european_only(chain)
        chain = chain[pd.to_datetime(chain["trade_date"]).dt.year == year]
        pairs = thinner_leg(chain)
        by_year[year] = table(pairs["parity_tested"].to_numpy(), pairs["flag_parity"].to_numpy(), pairs["thinner"].to_numpy(), len(chain))
        parts.append(pairs[["parity_tested", "flag_parity", "thinner"]])
        rows += len(chain)
        print(year, len(chain), flush=True)
    allp = pd.concat(parts, ignore_index=True)
    res = table(allp["parity_tested"].to_numpy(), allp["flag_parity"].to_numpy(), allp["thinner"].to_numpy(), rows)
    tested = allp["parity_tested"].to_numpy()
    rep = {"period": "2015-2022", "exercise_style": "european", "european_rows": rows, "pairs": len(allp), "tested_pairs": int(tested.sum()),
           "flag_rate_all_tested": float(allp["flag_parity"].to_numpy().sum() / tested.sum()), "candidates": res, "by_year": by_year, "chosen": pick(res)}
    out = ROOT / "reports" / "features"
    out.mkdir(parents=True, exist_ok=True)
    (out / "threshold.json").write_text(json.dumps(rep, indent=1), encoding="utf-8")
    print(json.dumps({k: rep[k] for k in rep if k != "by_year"}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
