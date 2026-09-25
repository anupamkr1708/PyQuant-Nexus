# Backtest Methodology

This document exists specifically because the refactor brief (Section 91)
requires the distinction between these five things to never be blurred in
terminology or output tables.

## 1. Signal generation
`strategy/signal_engine.build_stock_feature_frame` + the boolean Entry A-E
columns. A signal is just a fact about history: "on date D, condition X was
true." No P&L, no execution, no capital involved yet.

## 2. Event study (`research/event_study.py`)
"What happened after these signals?" Forward returns at fixed horizons (1/3/5/
10/20/40D by default), MFE/MAE, time-to-MFE/MAE. Descriptive only. Signals from
the same stock are correlated/overlapping — `stock_concentration_check` and
`block_bootstrap_ci` exist specifically so this isn't mistaken for independent
observations. **An event study is never presented as a tradable P&L.**

## 3. Portfolio backtest (`research/backtest.py`)
"What would an actual rule-driven portfolio have done?" Stateful: cash,
concurrent-position limits, position sizing from real capital, transaction
costs, a trade log, a daily equity curve. **This is new code the source
notebook does not have at all** (it only implements an event study) — built to
brief Section 49's spec, and NOT yet validated against real market data in
this environment (no network access here; see RESEARCH_LIMITATIONS.md). Known
simplifications are documented in the module's own docstring (long-only, one
position per symbol, first-come entry ordering, cash-timing approximation).

## 4. Walk-forward analysis (`research/walk_forward.py`)
Two distinct modes, never conflated:
- **Mode 1 (fixed-spec rolling OOS)**: the frozen 10/20/89/200 strategy
  evaluated across rolling out-of-sample folds. This is what the source
  notebook actually implements, despite sometimes being loosely called
  "walk-forward" — it optimizes nothing.
- **Mode 2 (true walk-forward)**: for each fold, select an EMA-period
  combination using ONLY the training window, freeze it, evaluate on the test
  window. New code (brief Section 51), deliberately simple (grid search on
  training-window median return) — a first pass, not a validated pipeline.

## 5. Parameter sensitivity (`research/sensitivity.py`)
Not a search for the best parameters. Perturbs one EMA role at a time around
the base spec and reports the full distribution (mean/median/std/spread)
alongside the best cell, specifically so a genuine plateau is distinguishable
from an overfit spike (brief Sections 29-30, 58).

## Execution and cost handling (applies to #2, #3, #4)

- Signal date != execution date. `execution/execution_models.py` resolves a
  modeled fill (`same_close`/`next_open`/`next_close`) via the real exchange
  calendar's `next_session`, never `date + 1 day`.
- A resolved price is labeled `NEXT_SESSION_EXECUTION_REFERENCE` unless
  `is_actual_fill=True` is explicitly supplied from a real broker execution —
  it is never presented as an actual fill.
- Stops model gap-through: if a session's Open has already passed the stop,
  the fill is at Open (`STOP_GAP_THROUGH`), not at the stop price.
- Transaction costs are PLACEHOLDER_UNVERIFIED (see RESEARCH_LIMITATIONS.md);
  cost SCENARIOS (zero/low/base/high) let a result be stress-tested even
  though the base numbers themselves are unverified.

## Universe methodology and survivorship bias

Every research run must be labeled with its `UNIVERSE_MODE`:
- `POINT_IN_TIME_NIFTY200` — only possible with a real historical-membership
  data source, which is **not wired up** in this refactor (same gap as the
  source notebook — see NOTEBOOK_AUDIT.md §2).
- `CURRENT_NIFTY200_HISTORICAL_SIMULATION` — the default and only mode
  currently available; using today's constituent list to run history is
  survivorship-biased and is labeled as such everywhere it appears (CLI
  output, run manifest, report headers). **Never described as an "unbiased
  historical NIFTY 200 backtest" anywhere in this codebase.**
