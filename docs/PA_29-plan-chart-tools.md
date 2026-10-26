# PA-29 — Plan chart: decluttered, larger, layer toggles, automatic marks, drawing tools

| | |
|---|---|
| **Status** | Done |
| **Scope** | `webapp/static/app.js` (Plan tab chart: `PlanOverlay`, `planChart`, `pcToolbar`, `drawPlanChartLines`), `webapp/static/style.css` (`.pc-*`, `--day`, `--draw`) |
| **Related** | [PA-22](PA_22-morning-plan.md), [PA-24](PA_24-trade-ticket-and-premium-levels.md), [PA-27](PA_27-pulse-trade-ranking.md) |
| **Pull request** | branch `feature/plan-chart-tools` |
| **Date** | 2026-10-26 |

## 1. Problem

The user's screenshot showed the Plan chart too cluttered to read:

- about ten price lines, each with an axis label;
- the labels stacked on top of each other at the right edge;
- a chart only 300 px tall.

They asked for:

- a clean, larger chart;
- complete marking tools;
- everything marked automatically.

## 2. Change

### Clean

- **Height.** 460 px (360 px on phones).
- **Grid.** No vertical grid lines; dashed dividers between sessions instead.
- **Axis labels.** Only the last price, the target and the stop take one.
- **Other levels.** Labelled inside the chart at the left edge, nudged apart so they never overlap.
- **Zones.** The entry zone and the expected range are soft bands. The trade is drawn like a position:
  - a green zone from the entry to the target;
  - a red zone from the entry to the stop;
  - both right of the last candle.
- **Scale.** The price scale always takes in the trade's entry, target and stop, so the stop is never off the chart.

### Layers (toolbar chips, also the legend)

Each chip turns its layer on or off. The choice is kept in this browser for both index charts.

| Layer | What it draws |
|---|---|
| Averages | EMA 9 and EMA 21 |
| Trade | Entry, target and stop: the rules signal and the selected ranked / AI trade |
| Expected range | The day's expected high and low (GARCH) |
| Option walls | Call wall and put wall (biggest OI) |
| Day levels | Previous session's high, low and close; today's open (automatic) |
| Swings | Swing highs and lows: the extreme of the 12 candles (an hour) either side (automatic) |
| Crossovers | EMA 9 / 21 crosses: green up, red down (automatic) |

The option strike of the selected leg is still drawn when its ticket is open.

### Zoom

**Today / 2D / 5D / All** set the visible range. The choice is remembered.

### Drawing tools

- **Line.** Click a price to place a horizontal line, labelled with its price.
- **Trend.** Click two candles; a dashed preview follows the cursor.
- **Undo** removes the last line; **Clear** removes them all (after confirming). Esc cancels a tool.
- **Storage.** Lines are kept per instrument in this browser (`localStorage`), not on the server.

### Readout

A row above the chart shows the candle under the cursor (the last candle otherwise):

- its time;
- O / H / L / C and its change;
- EMA 9 and EMA 21.

## 3. Checked

Checked in headless Chrome against the live server, with real mouse clicks over the DevTools protocol:

- a horizontal line and a trend line placed, with the hints updating;
- Undo removed the last line;
- layer and zoom choices saved;
- the readout followed the cursor;
- light and dark themes;
- a 420 px phone width;
- no page errors.

At phone width the whole Plan page is wider than the screen: the session card and the trade table are cut off too.
That was already so on `main` and is not changed here.
