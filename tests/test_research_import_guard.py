"""New model and backtest code must read the store through tradingagents.research.loader (docs/PA_31).

Any file that reaches the store another way (importing datastore, prices, backfill or holdout, or calling
store_root / raw_root / data_cache_dir) must be listed in ALLOWED with the reason. The list was measured on
2026-10-27: the live pipeline and the experiments that ran before the split was frozen. Adding to it is a
visible decision in review; research code under tradingagents/research/ (except the loader) and
scripts/research_*.py may never be added.
"""

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCANNED = ("tradingagents", "scripts", "webapp", "cli")
UNLOCKED_MODULES = {"datastore", "prices", "backfill", "holdout"}
UNLOCKED_NAMES = {"store_root", "raw_root", "data_cache_dir", "prices_path", "raw_path"}

LIVE = "live pipeline (nightly refresh, paper trading, web app or agents): untouched by the research lock"
PRE_SPLIT = "experiment run before the split was frozen (2026-10-27); kept for reproducibility"
INGEST = "builds or audits the store itself"
CACHE = "uses data_cache_dir for its own HTTP or config cache, not the quant store"
ALLOWED = {
    # the store and its builders
    "tradingagents/analytics/datastore.py": INGEST,
    "tradingagents/analytics/prices.py": INGEST,
    "tradingagents/analytics/backfill.py": INGEST,
    "tradingagents/analytics/quotes.py": INGEST,
    "tradingagents/analytics/trial_log.py": INGEST,
    "tradingagents/analytics/paper.py": LIVE,
    "scripts/quant_backfill.py": INGEST,
    "scripts/quant_build_store.py": INGEST,
    "scripts/quant_daily_update.py": LIVE,
    "scripts/update_progress.py": LIVE,
    "scripts/market_map.py": LIVE,
    "tradingagents/analytics/quant_report.py": LIVE,
    # vendor and app caches
    "tradingagents/dataflows/vendors/nse/client.py": CACHE,
    "tradingagents/dataflows/vendors/nse/derivatives.py": CACHE,
    "tradingagents/dataflows/vendors/nse/flows.py": CACHE,
    "tradingagents/dataflows/vendors/nse/indices.py": CACHE,
    "tradingagents/dataflows/vendors/sec_edgar.py": CACHE,
    "tradingagents/dataflows/vendors/yahoo/ohlcv.py": CACHE,
    "tradingagents/default_config.py": CACHE,
    "tradingagents/graph/trading_graph.py": CACHE,
    "cli/main.py": CACHE,
    "webapp/morning.py": LIVE,
    "webapp/option_chain.py": LIVE,
    "webapp/quant.py": LIVE,
    # experiments before the freeze
    "tradingagents/analytics/vrp.py": PRE_SPLIT,
    "tradingagents/analytics/holdout.py": PRE_SPLIT,
    "tradingagents/analytics/events.py": PRE_SPLIT,
    "tradingagents/analytics/ml/inputs.py": PRE_SPLIT,
    "scripts/quant_chronos.py": PRE_SPLIT,
    "scripts/quant_evaluate.py": PRE_SPLIT,
    "scripts/quant_ml.py": PRE_SPLIT,
    "scripts/quant_move_size.py": PRE_SPLIT,
    "scripts/quant_quiet_condor.py": PRE_SPLIT,
    "scripts/quant_regime.py": PRE_SPLIT,
    "scripts/quant_relative.py": PRE_SPLIT,
    "scripts/quant_results_fly.py": PRE_SPLIT,
    "scripts/quant_stress.py": PRE_SPLIT,
    "scripts/quant_vol_forecasts.py": PRE_SPLIT,
    "scripts/quant_vrp_condor.py": PRE_SPLIT,
    "scripts/quant_holdout.py": PRE_SPLIT,
    # the research layer's own door and its audit
    "tradingagents/research/loader.py": "the locked loader itself",
    "scripts/research_check_pit.py": "point-in-time audit of the whole store (counts, no model)",
}
NEVER_ALLOWED_PREFIXES = ("tradingagents/research/", "scripts/research_")
NEVER_ALLOWED_EXCEPT = {"tradingagents/research/loader.py", "scripts/research_check_pit.py"}


def reaches_store(path: Path) -> list[str]:
    """How a file reaches the store directly, if it does."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    hits = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            mod = node.module.split(".")
            if mod[:2] == ["tradingagents", "analytics"] and len(mod) > 2 and mod[2] in UNLOCKED_MODULES:
                hits.append(f"from {node.module} import ...")
            elif node.module == "tradingagents.analytics":
                hits += [f"from tradingagents.analytics import {a.name}" for a in node.names
                         if a.name in UNLOCKED_MODULES]
        elif isinstance(node, ast.Import):
            hits += [f"import {a.name}" for a in node.names
                     if a.name.split(".")[:2] == ["tradingagents", "analytics"]
                     and len(a.name.split(".")) > 2 and a.name.split(".")[2] in UNLOCKED_MODULES]
        elif isinstance(node, ast.Name) and node.id in UNLOCKED_NAMES:
            hits.append(node.id)
        elif isinstance(node, ast.Attribute) and node.attr in UNLOCKED_NAMES:
            hits.append(f".{node.attr}")
        elif isinstance(node, ast.Constant) and node.value == "data_cache_dir":
            hits.append('"data_cache_dir"')
    return sorted(set(hits))


def _files():
    for top in SCANNED:
        for p in sorted((ROOT / top).rglob("*.py")):
            if "__pycache__" not in p.parts:
                yield p.relative_to(ROOT).as_posix(), p


@pytest.mark.unit
def test_only_allowed_files_reach_the_store_directly():
    offenders = {rel: reaches_store(p) for rel, p in _files() if rel not in ALLOWED and reaches_store(p)}
    assert not offenders, ("read the store through tradingagents.research.loader, or add the file to ALLOWED "
                           f"with a reason: {offenders}")


@pytest.mark.unit
def test_research_code_is_never_allowed_an_unlocked_path():
    bad = [rel for rel in ALLOWED if rel.startswith(NEVER_ALLOWED_PREFIXES) and rel not in NEVER_ALLOWED_EXCEPT]
    assert not bad


@pytest.mark.unit
def test_allowed_list_has_no_stale_entries():
    stale = [rel for rel in ALLOWED if not (ROOT / rel).is_file()]
    assert not stale


@pytest.mark.unit
def test_guard_catches_a_model_reading_the_store(tmp_path):
    for source in ("from tradingagents.analytics import datastore as ds\n",
                   "from tradingagents.analytics.prices import load_prices\n",
                   "import tradingagents.analytics.backfill\n",
                   "from tradingagents.dataflows.config import get_config\nroot = get_config()['data_cache_dir']\n",
                   "from tradingagents.analytics import datastore\npath = datastore.store_root()\n"):
        f = tmp_path / "model.py"
        f.write_text(source, encoding="utf-8")
        assert reaches_store(f), source
    f.write_text("from tradingagents.research import loader\ndf = loader.load('fo_summary')\n", encoding="utf-8")
    assert not reaches_store(f)
