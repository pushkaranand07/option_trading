"""Research layer: frozen data splits and the locked loader that every new model or backtest reads through.

The live pipeline (nightly refresh, paper trading, web app, agents) keeps reading the store directly; new
research code may not (tests/test_research_import_guard.py).
"""
