"""TradingAgents' entry point to the options engine (``option_backtester``).

The engine came from the separate optopsy project and now lives in this
repository as the top-level ``option_backtester`` package (AGPL-3.0, see its
LICENSE). Only the engine was brought over — strategies, entry signals,
pricing/evaluation, exits, metrics and the simulator. optopsy's chat UI and
its EODHD downloader/cache were left out: TradingAgents is the agent layer, and
Indian option chains come from NSE bhavcopies (``adapter.bhavcopy_to_optopsy``).

It runs in TradingAgents' own environment. Its two extra dependencies are
pinned to the versions optopsy was tested with (``pandas-ta-classic``,
``empyrical-reloaded``); ``doctor()`` reports what is installed.
"""

from __future__ import annotations

import importlib
import inspect
import pkgutil
import platform

import pandas as pd


class OptopsyUnavailableError(RuntimeError):
    """The options engine or one of its dependencies cannot be imported."""


def _engine():
    try:
        return importlib.import_module("option_backtester")
    except ImportError as exc:
        raise OptopsyUnavailableError(
            f"options engine unavailable ({exc}); install TradingAgents' dependencies "
            "(pip install -e .), which include pandas-ta-classic and empyrical-reloaded"
        ) from exc


def _public_functions(module) -> dict:
    out = {}
    for name, fn in inspect.getmembers(module, inspect.isfunction):
        if name.startswith("_") or fn.__module__ != module.__name__:
            continue
        doc = (inspect.getdoc(fn) or "").strip().splitlines()
        out[name] = {"summary": doc[0] if doc else "", "signature": str(inspect.signature(fn)),
                     "module": module.__name__}
    return out


class OptopsyBridge:
    """Run options-engine strategies and list what the engine offers."""

    def __init__(self):
        self.engine = _engine()

    def info(self) -> dict:
        import empyrical
        import numpy
        import pandas_ta_classic

        return {"python": platform.python_version(), "pandas": pd.__version__, "numpy": numpy.__version__,
                "option_backtester": self.engine.__version__, "location": self.engine.__file__,
                "pandas_ta_classic": getattr(pandas_ta_classic, "version", "?"),
                "empyrical": getattr(empyrical, "__version__", "?")}

    def list_components(self) -> dict:
        """{"strategies": {name: {summary, signature, module}}, "signals": {...}}"""
        found = {}
        for kind in ("strategies", "signals"):
            package = importlib.import_module(f"option_backtester.{kind}")
            found[kind] = {}
            for info in pkgutil.iter_modules(package.__path__):
                if not info.name.startswith("_"):
                    module = importlib.import_module(f"{package.__name__}.{info.name}")
                    found[kind].update(_public_functions(module))
        return found

    def run_strategy(self, name: str, chain: pd.DataFrame, **params) -> pd.DataFrame:
        """Run a strategy on a chain in the engine's schema (see ``adapter``).

        For vertical spreads pass distinct ``leg1_delta`` / ``leg2_delta``: the
        engine defaults both legs to 0.30 delta, which lands them on the same
        strike and yields an empty result.
        """
        fn = getattr(self.engine, name, None)
        if fn is None or not callable(fn):
            raise ValueError(f"unknown options strategy {name!r}")
        chain = chain.copy()
        # pandas 3 builds Timestamps from dates at second resolution; the engine's
        # schema check accepts only ns/us.
        for col in ("expiration", "quote_date"):
            if col in chain:
                chain[col] = pd.to_datetime(chain[col]).astype("datetime64[us]")
        return fn(self.engine.options_data(chain), **params)

    def doctor(self) -> dict:
        try:
            return {"healthy": True, **self.info()}
        except Exception as exc:     # a missing dependency is the answer, not a crash
            return {"healthy": False, "error": f"{type(exc).__name__}: {exc}"}
