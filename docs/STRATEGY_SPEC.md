# Strategy Specification (frozen — `STRATEGY_VERSION = "ema_cluster_v1"`)

Every production rule in this codebase must trace back to this document (brief
Section 89: "no drift requirement"). If a mathematical rule ever needs to
change, bump `STRATEGY_VERSION` in `src/ema_scanner/__init__.py` — never edit
v1's behavior silently. Full traceability to the source notebook is in
`NOTEBOOK_AUDIT.md`.

## 1. EMA definitions

Role names `EMA10`/`EMA20`/`EMA89`/`EMA200` refer to PERIODS 10/20/89/200 by
default (`configs/default.yaml: strategy.ema`), configurable but never silently
changed. Recursion:

```
EMA_t = (Price_t - EMA_{t-1}) * (2 / (period + 1)) + EMA_{t-1}
```

Seed (`seed_method: sma`, default): `EMA_{period-1} = mean(Price_0..Price_{period-1})`,
recursion from bar `period`. Alternative `first_obs`: `EMA_0 = Price_0`. Neither
seed is asserted "correct" — see `docs/NOTEBOOK_AUDIT.md` row 2.

## 2. Alignment (strict inequalities only)

```
BULLISH_ALIGNED: EMA10 > EMA20 > EMA89 > EMA200
BEARISH_ALIGNED: EMA10 < EMA20 < EMA89 < EMA200
MIXED:           otherwise
```

## 3. Crossovers

```
bullish(A,B): A[t-1] <= B[t-1] AND A[t] > B[t]
bearish(A,B): A[t-1] >= B[t-1] AND A[t] < B[t]
```
Six pairs tracked independently: (10,20) (20,89) (89,200) (10,89) (10,200) (20,200).

## 4. Weekly context

Weekly OHLC aggregated from actual trading sessions grouped by (ISO year, ISO
week) — not a fixed `W-FRI` anchor. A weekly row is eligible for use on daily
date `D` once `WeekEnd <= D` (non-strict). See `NOTEBOOK_AUDIT.md §3` for why
this differs from the source notebook's strict `<`.

## 5. Cluster + Definitions A-D

`Cluster_Width_Pct = (max(4 EMAs) - min(4 EMAs)) / Close * 100`. Compression /
expansion states use a ROLLING PERCENTILE of width (default lookback 252
sessions; compression <=20th pctl, expansion >=80th pctl) — RESEARCH_HYPOTHESIS.

Four independent interpretations of "EMA cluster crossover" (none merged, none
asserted correct — the source note itself does not give one precise definition):

- **A — Sequential crossover**: EMA10xEMA20, then EMA20xEMA89, then
  EMA89xEMA200, each within `sequential_crossover_max_gap_sessions` (default 10).
- **B — Alignment transition**: state flips from non-bullish to
  BULLISH_ALIGNED.
- **C — Price-through-cluster**: price was `<=` cluster max, is now `>` all
  four EMAs.
- **D — Compression-then-expansion**: cluster was compressed within
  `compression_expansion_lookahead_days` (default 10) and is now EXPANDING
  with `Close > Cluster_Center`.

## 6. Entry models A-E (long side only — see §9)

- **A — Fresh alignment**: `Daily_State` transitions into BULLISH_ALIGNED.
- **B — Cluster breakout**: price crosses above the cluster maximum.
- **C — Pullback continuation**: prior SHALLOW/MODERATE pullback, price
  reclaims EMA20.
- **D — Swing-high breakout**: price breaks the latest CONFIRMED swing high
  while BULLISH_ALIGNED.
- **E — Reclaim after pullback**: prior SHALLOW/MODERATE/DEEP pullback, price
  reclaims the cluster center, structure not BEARISH_ALIGNED.

Each is an independent boolean column. None is "the" strategy; the scanner
reports which model(s) triggered.

## 7. Swing structure (no-lookahead invariant)

Fractal pivot at bar `t` with `left`/`right` window (default 5/5) is CONFIRMED
at bar `t + right`. Every downstream consumer (stops, Entry D) uses the
confirmation date, never the swing date, as the availability boundary.

## 8. Stops, sizing, execution, costs

- **Stop (long)**: latest CONFIRMED swing low. ATR-based stop
  (`atr_stop_multiple`, default 2.5) is a SEPARATE, OPTIONAL diagnostic —
  never substituted for the swing stop.
- **Sizing**: `qty = floor((equity * risk_per_trade_pct/100) / |entry - stop| / lot_size) * lot_size`.
- **Execution models**: `same_close` / `next_open` / `next_close`, resolved via
  the exchange calendar's `next_session`, never `date + 1 day`.
- **Costs**: PLACEHOLDER_UNVERIFIED (brokerage/STT/exchange/GST/slippage) —
  confirm against your actual broker before trusting net figures.

## 9. Explicit scope limits (not silently invented)

- **Long side only.** The source note's point 8 ("reverse logic exists
  conceptually for shorts") is not implemented as trading logic anywhere —
  the notebook itself never implements the short side either.
- **No single universal exit.** The source note specifies entries and the
  swing stop, not one profit-taking framework. `research/backtest.py` supports
  two explicitly-labeled `RESEARCH_HYPOTHESIS` exit rules
  (`STOP_ONLY_RESEARCH`, `FIXED_HORIZON`) — see its module docstring.
- **Heuristic score is diagnostic only** (`strategy/scoring.py`). It is never
  the trading decision and never called a probability/confidence anywhere in
  this codebase.

## 10. Market regime, relative strength, liquidity — diagnostics first

Regime (`BULL`/`BEAR`/`NEUTRAL` on index `price>EMA50>EMA200`), relative
strength (20/60/120D vs. benchmark), and liquidity are all OPTIONAL /
diagnostic-first: reported for segmentation, never auto-applied as filters
unless explicitly enabled in config.
