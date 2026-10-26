# Agents and tools

> **Status:** Current.
> **Scope:** every agent role under `tradingagents/agents/`, what each reads from and writes to the state, which
> data tools each analyst can call (`tradingagents/agents/tools.py`), and how the Portfolio Manager decides.
> **Last verified against the code:** 2026-10-24

---

## 1. The roles at a glance

| Node name | File | Model tier | Reads from state | Writes to state |
|---|---|---|---|---|
| Market Analyst | `analysts/market_analyst.py` | quick | `trade_date`, `instrument_context`, own messages | `market_report` |
| Sentiment Analyst | `analysts/sentiment_analyst.py` | quick | `company_of_interest`, `trade_date`, `instrument_context` | `sentiment_report` |
| News Analyst | `analysts/news_analyst.py` | quick | `trade_date`, `asset_type`, `instrument_context`, own messages | `news_report` |
| Fundamentals Analyst | `analysts/fundamentals_analyst.py` | quick | `trade_date`, `instrument_context`, own messages | `fundamentals_report` |
| Memory Log | `graph/trading_graph.py` (`_memory_step`) | quick (for reflections) | `company_of_interest`, `trade_date` | `past_context`, `memory_note` |
| Bull Researcher | `researchers/bull_researcher.py` | quick | four reports, `investment_debate_state` | `investment_debate_state` |
| Bear Researcher | `researchers/bear_researcher.py` | quick | four reports, `investment_debate_state` | `investment_debate_state` |
| Research Manager | `managers/research_manager.py` | **deep** | `investment_debate_state.history` | `investment_plan`, `investment_debate_state` |
| Trader | `trader/trader.py` | quick | `investment_plan`, `market_report`, `portfolio_context` | `trader_investment_plan` |
| Aggressive / Conservative / Neutral Analyst | `risk_mgmt/*_debator.py` | quick | four reports, `trader_investment_plan`, `portfolio_context`, `risk_debate_state` | `risk_debate_state` |
| Portfolio Manager | `managers/portfolio_manager.py` | **deep** | `risk_debate_state.history`, `investment_plan`, `trader_investment_plan`, `past_context`, `portfolio_context` | `final_trade_decision`, `final_rating`, `risk_debate_state` |

Model tiers are assigned in `GraphSetup.setup_graph()` (`tradingagents/graph/setup.py`). Every agent's prompt
includes the instrument context (`get_instrument_context_from_state`) and the output-language instruction
(`get_language_instruction`).

Shared helpers in `tradingagents/agents/context.py`:

- `report_or_absent()` — an empty report is shown as "(No … report in this run: it is not available, not an
  empty finding.)" so a reader agent does not invent its content.
- `opponent_argument_or_opening()` — the same for an opponent who has not spoken yet.
- `get_portfolio_context_from_state()` — without a portfolio file, agents are told the holdings are unknown and
  must not assume a flat book.

## 2. Analysts and their tools

Each tool-using analyst has a `TOOLS` tuple; its tool node is built from the same tuple
(`tradingagents/graph/analyst_execution.py`). A turn is run by `take_turn()` in `analysts/turn.py`: the report
stays empty while the model is still calling tools.

| Analyst | Tools |
|---|---|
| Market | `get_stock_data`, `get_indicators`, `get_verified_market_snapshot`, `get_india_index_data_health`, `get_india_delivery_data`, `get_india_fo_contract_info`, `get_quant_signal_report` |
| News | `get_news`, `get_global_news`, `get_macro_indicators`, `get_prediction_markets`, `get_india_fii_dii_flows` |
| Fundamentals | `get_fundamentals`, `get_balance_sheet`, `get_cashflow`, `get_income_statement`, `get_insider_transactions` |
| Sentiment | none (data is fetched before the model is called) |

**Market Analyst.** Picks up to 8 indicators from a fixed list (50/200 SMA, 10 EMA, MACD family, RSI, Bollinger
bands, ATR, VWMA). It is told to call `get_stock_data` first, to treat `get_verified_market_snapshot` as the
source of truth for exact prices and indicator values, and, for NSE F&O stocks, NIFTY and BANKNIFTY, to quote
`get_quant_signal_report` and repeat its validation status: "a quant number that has not passed validation is
context about risk, never a reason to buy or sell."

**Sentiment Analyst.** Fetches three sources for the 7 days up to the trade date: Yahoo Finance headlines
(through `get_news`), StockTwits messages, and Reddit posts (r/wallstreetbets, r/stocks, r/investing, or
crypto subreddits). If `TYPESAFE_API_KEY` is set, social posts are first screened by TypeSafe's Jev model
(`agents/post_screen.py`): off-topic posts are dropped and a stance count is added. Output is a
`SentimentReport` (band, 0–10 score, confidence, narrative). The code notes these feeds are not archived, so a
historical run's sentiment inputs are not point-in-time.

**News Analyst.** Company news, global macro news (search queries from `global_news_queries`), FRED macro
series, Polymarket probabilities, and NSE FII/DII flows; its prompt names all five tools
([the small-fixes change](../development/testing-and-lint.md)).

**Fundamentals Analyst.** Company overview, the three statements (SEC EDGAR as filed for US filers, then
Yahoo, per `data_vendors.fundamental_data`), and insider transactions.

## 3. Tool rules

All tools are in `tradingagents/agents/tools.py`.

- The ticker comes from state (`InjectedState("company_of_interest")`); the model cannot change it.
- Every dated tool also receives the run's `trade_date` from state and never serves data past it, whatever date
  the model asks for (`as_of`, `as_of_window` in `tradingagents/dataflows/date_window.py`).
- Requests go through `route_to_vendor()` (`tradingagents/dataflows/router.py`) to the vendors configured in
  `data_vendors` / `tool_vendors` ([06](06-data-vendors.md)).
- A vendor failure becomes a text answer, not an exception, so one bad source does not end the run.
- The four `get_india_*` tools answer "not applicable" for instruments not listed on NSE
  ([07](07-india-market-layer.md)).

**`get_quant_signal_report(curr_date)`** calls `quant_signal_text()` in
`tradingagents/analytics/quant_report.py`. It reads only precomputed outputs (market regime, GARCH and EWMA
volatility forecasts, 30-day implied volatility, the trial log), and only values known before the date's open.
Every number carries its validation status. Details: [16](16-quant-context-in-agents.md).

## 4. Researchers and Research Manager

Bull and Bear each make one LLM call per turn, prefix their text with "Bull Analyst:" / "Bear Analyst:",
append it to the debate histories and add 1 to `count`.

The Research Manager reads the debate history and returns a `ResearchPlan` (structured output): a
recommendation on the 5-tier scale, a rationale, and strategic actions. It is told that conflict alone is not
a reason to Hold.

## 5. Trader

The Trader reads the investment plan and, when the Market Analyst ran, the market report, so entry and stop
levels rest on real price structure. It returns a `TraderProposal`: action Buy / Hold / Sell (Overweight maps
to Buy, Underweight to Sell), reasoning, and optional entry price, stop-loss (absolute prices, never
percentages) and position sizing.

## 6. Risk debaters

Each of the three reads all four reports, the trader's plan and the portfolio block, answers the other two,
and writes its argument with `latest_speaker` set to "Aggressive", "Conservative" or "Neutral". Order is fixed:
Aggressive, Conservative, Neutral ([02](02-agent-pipeline.md)).

## 7. How the Portfolio Manager decides

Input: the Research Manager's plan, the Trader's proposal, the full risk-debate history, the portfolio block
and, when the memory log has any, "Lessons from prior decisions and outcomes" (`past_context`).

Instructions in the prompt:

- Use exactly one rating: Buy, Overweight, Hold, Underweight, Sell.
- Conflict alone is not a reason to Hold; commit to the stronger case, sized by how decisively it wins. Hold
  only when the evidence is still balanced or too thin.
- Quant figures may inform size and risk, but a quant signal supports a direction only if the quant report
  lists it under "Approved signals". An argument resting on an unvalidated quant signal must be discounted.

Output: a `PortfolioDecision` (`agents/schemas.py`) with `rating`, `executive_summary`, `investment_thesis`, and
optional `price_target` and `time_horizon`. `final_rating` is the typed `rating`; `final_trade_decision` is
the decision rendered to Markdown by `render_pm_decision()`.

If the provider has no structured output or the structured call fails, the agent falls back to free text and
`parse_rating()` reads the rating from a "Rating: X" line. If none can be read the result is `REVIEW`
(`agents/rating.py`).

## 8. Structured output

`agents/structured.py` wraps the Research Manager, Trader, Portfolio Manager and Sentiment Analyst models with
`with_structured_output(Schema)`. If binding is not supported, or a structured call fails, they fall back to a
plain call. These agents are told not to call external tools (`NO_EXTERNAL_TOOLS`), because a tool call in a
structured attempt discards it.
