# Notebook Audit & Traceability Matrix

**Source of truth audited:** `notebooks/Nifty200_EMA_Cluster_Research.ipynb` (49 cells, unmodified,
kept in this repo as historical research provenance).

This document was written **before** any refactor code was produced, per the refactor brief's
Section 1 ("fully audit the notebook before modifying it"). Every rule below is traced to its
originating cell, its label as used *in the notebook itself* (the notebook already tags rules as
SOURCE-DERIVED RULE / MATHEMATICAL DEFINITION / RESEARCH HYPOTHESIS / OPTIONAL FILTER /
EMPIRICALLY TESTED RESULT), and the new module that now implements it.

---

## 1. Inventory of rules, by cell

| # | Cell(s) | What it defines | Label (as given in notebook) | New module |
|---|---|---|---|---|
| 1 | 6 (Config) | EMA10/20/89/200 periods | SOURCE-DERIVED RULE | `strategy/specification.py`, `configs/default.yaml` |
| 2 | 6 | EMA seed method = `sma` (seed at bar N-1 with SMA of first N obs, then recurse); alt `first_obs` | MATHEMATICAL DEFINITION | `features/ema.py` |
| 3 | 6 | Swing left=5, right=5 (confirmation lag) | SOURCE/ENGINEERING (lag is structural to the no-lookahead rule; the *value* 5/5 is a default, not asserted optimal) | `features/swing.py` |
| 4 | 6 | ATR period = 14 | SOURCE-DERIVED (explicitly requested: "Preserve ATR14") | `features/volatility.py` |
| 5 | 6 | Cluster width lookback 252, compression pctl 0.20, expansion pctl 0.80 | RESEARCH HYPOTHESIS | `features/cluster.py` |
| 6 | 6 | Sequential crossover max gap = 10 sessions | RESEARCH HYPOTHESIS | `strategy/definitions.py` |
| 7 | 6 | Pullback ATR bands 1.0 / 2.5 / 4.0 | RESEARCH HYPOTHESIS | `features/pullback.py` |
| 8 | 6 | Risk/trade 0.5%, ATR stop multiple 2.5 | OPTIONAL / user-set | `execution/sizing.py`, `execution/stops.py` |
| 9 | 6 | Execution model default `next_open` | ENGINEERING_DECISION (source note doesn't specify fill timing; notebook explicitly separates detection/execution) | `execution/execution_models.py` |
| 10 | 6 | Cost placeholders (brokerage/STT/exchange/GST/slippage) | PLACEHOLDER, notebook says "user must confirm" | `execution/costs.py` |
| 11 | 6 | Liquidity filter OFF by default | OPTIONAL FILTER | `strategy/filters.py` |
| 12 | 8 | NIFTY 200 universe fetched live, never hard-coded; fails loudly on error | SOURCE-DERIVED RULE | `universe/current.py` |
| 13 | 8 | `label_universe_mode()` — always returns `CURRENT-UNIVERSE HISTORICAL SIMULATION` (no historical membership source wired up) | **Notebook's own honest gap**, explicitly disclosed | `universe/historical.py` (interface only, same gap preserved and now formalized) |
| 14 | 10 | yfinance data layer + parquet cache keyed by `(symbol, start, end)` | ENGINEERING (data plumbing) | `data/yfinance.py`, `data/cache.py` |
| 15 | 12 | `validate_ohlc` — duplicate dates, monotonicity, non-positive prices, High/Low consistency, staleness, abnormal-gap flags | SOURCE-DERIVED (Section 36 of brief maps directly onto this) | `data/quality.py` |
| 16 | 14 | `compute_ema` — explicit recursion, SMA seed | MATHEMATICAL DEFINITION | `features/ema.py` |
| 17 | 16 | `build_true_weekly_ohlc` (W-FRI resample) + `attach_last_known_weekly` (as-of, **strict `<`**) | SOURCE-DERIVED RULE (weekly=context, no leakage) + one MATHEMATICAL DEFINITION that the refactor brief explicitly flags as **more conservative than necessary** | `features/weekly.py` (info-availability model rebuilt; see §3 below) |
| 18 | 18 | `classify_alignment` (strict `>`/`<`), `bullish_crossover`/`bearish_crossover`, 6 EMA pairs, MTF matrix | MATHEMATICAL DEFINITION | `features/alignment.py`, `features/crossover.py` |
| 19 | 20 | Cluster width/center/pair distances; compression (rolling percentile ≤0.20); expansion state (FLAT/EXPANDING/CONTRACTING via 5D width-change quantile band) | RESEARCH HYPOTHESIS | `features/cluster.py` |
| 20 | 20 | Definitions A (sequential crossover, ≤10-session gap), B (alignment transition), C (price-through-cluster), D (compression→expansion+bullish bias) | RESEARCH HYPOTHESIS ×4, kept **independent**, never merged | `strategy/definitions.py` |
| 21 | 22 | `compute_ema_slopes` (K=10 %-change, not "annualized"); `compute_atr` (Wilder-style EWM, `adjust=False`, `min_periods=period`) | MATHEMATICAL DEFINITION | `features/volatility.py` |
| 22 | 24 | `detect_swing_points` (left/right fractal pivot), confirmation lag, `latest_confirmed_swing_low/high`, vectorized ffill versions | **CRITICAL no-look-ahead rule**, SOURCE-DERIVED | `features/swing.py` |
| 23 | 26 | `classify_pullback` — ATR-normalized distance below cluster center, conditioned on `ever_broke_out` (hard-coded 60-bar rolling window) | RESEARCH HYPOTHESIS (bands); **the 60-bar breakout-memory window was an unlabeled magic number** — now named `PULLBACK_BREAKOUT_MEMORY_BARS`, default unchanged | `features/pullback.py` |
| 24 | 28 | Entry models A (fresh alignment), B (cluster breakout), C (pullback continuation), D (swing-high breakout), E (reclaim after pullback) | RESEARCH HYPOTHESIS ×5, kept independent | `strategy/entries.py` |
| 25 | 30 | `compute_market_regime` — index EMA20/50/89/200, BULL/BEAR/NEUTRAL on `price>EMA50>EMA200` | OPTIONAL FILTER / diagnostic-only | `features/regime.py` |
| 26 | 32 | `compute_relative_strength` — 20/60/120D vs index; `cross_sectional_percentile` | SOURCE-DERIVED (Section 20 of brief) | `features/relative_strength.py` |
| 27 | 34 | `compute_stops` (swing-based + separate ATR-based diagnostic); `position_size`; `resolve_execution_price` (same_close/next_open/next_close); `compute_transaction_cost_pct` | SOURCE-DERIVED (stop = swing) + ENGINEERING (execution/sizing kept separate from signal) + PLACEHOLDER (costs) | `execution/stops.py`, `execution/sizing.py`, `execution/execution_models.py`, `execution/costs.py` |
| 28 | 36 | `build_stock_feature_frame` — the master per-stock pipeline; `compute_signal_state` (10-state machine); `compute_composite_heuristic_score` (explicitly labeled heuristic, never the trading rule); `generate_signal_reason` (deterministic, rule-derived text) | SOURCE-DERIVED + ENGINEERING | `strategy/signal_engine.py`, `strategy/state_machine.py`, `strategy/scoring.py` |
| 29 | 36 | Live-scan execution: universe fetch → batch download → `run_full_universe_pipeline` → `run_live_scan`; **uses `pd.Timestamp.today()`** for `start_date` and implicitly for "latest row" | ENGINEERING, and a **flagged bug** — see §4 below | `cli.py` (`scan` command), `calendar/sessions.py` (`resolve_analysis_date`) |
| 30 | 38 | Event-study engine: `event_study_forward_returns` (1/3/5/10/20/40D + MFE/MAE/time-to), `apply_transaction_costs`, `performance_stats`, `comparison_table`, `regime_breakdown` (mandatory), `stock_concentration_check` | EMPIRICALLY TESTED RESULT (methodology) | `research/event_study.py`, `research/statistics.py` |
| 31 | 40 | Walk-forward: `walk_forward_splits`, `walk_forward_research` — rolling **fixed-specification** OOS folds. **The notebook's own markdown already says this "does not genuinely train/optimize parameters" — it is Mode 1 (fixed-spec) only, no Mode 2 (train-then-freeze) exists in the notebook.** | Notebook's own honest label | `research/walk_forward.py` — Mode 1 ported as-is; Mode 2 (true nested train/test) is **new code**, explicitly labeled `ENGINEERING_DECISION`, see §5 |
| 32 | 42 | `ema_period_sensitivity` — perturbs one EMA role at a time around 10/20/89/200; `plateau_summary` (mean/median/std/spread, not just best) | SOURCE-DERIVED (Section 29/30: never call it "optimal") | `research/sensitivity.py` |
| 33 | 44 | Validation suite: EMA-vs-reference, crossover tests, alignment tests, cluster-width non-negativity, swing-confirmation-lag, **weekly no-lookahead**, **swing no-lookahead** (10 tests total) | SOURCE-DERIVED (Sections 37/38 of brief) | `tests/unit/*`, `tests/lookahead/*` — ported verbatim as regression tests, then extended |
| 34 | 46 | Excel export — percent-format fix (values stored as 0–1 fraction + `'0.00%'` cell format) | ENGINEERING (explicit bug-fix already in notebook) | `reporting/excel.py` |
| 35 | 48 | Final report + "Principal Engineer review" self-audit text | ENGINEERING | `reporting/manifest.py`, this document |

---

## 2. Notebook self-disclosed gaps (preserved, not silently fixed)

The notebook is unusually explicit about its own limitations. These are **not new findings** —
they are the notebook's own words, carried forward verbatim so the refactor doesn't quietly
resolve an ambiguity the original author left open on purpose:

1. *"The handwritten note does not give one precise mathematical definition of an 'EMA cluster
   crossover,' nor an exact entry timing after it."* → preserved as 4 independent Definitions
   (A–D) and 5 independent Entry models (A–E); the refactor does **not** collapse them.
2. *"No historical NIFTY-200 constituent history is wired up here"* → `universe_mode` is always
   `CURRENT-UNIVERSE HISTORICAL SIMULATION` in the notebook. The refactor preserves this exact
   behavior and formalizes the `PointInTimeUniverseProvider` interface for a **future** data
   source — it does not fabricate historical membership.
3. *"Transaction-cost assumptions in Config are placeholders and must be confirmed against the
   user's actual broker/exchange fee schedule."* → carried forward unchanged; the refactor adds
   cost *scenarios* (zero/low/base/high) but does not assert the base numbers are current or
   correct.
4. Walk-forward is a **rolling fixed-specification OOS evaluation**, not true walk-forward
   parameter optimization — the notebook says so in its own markdown. See §5.

## 3. A rule that needed a real fix, not a preservation (weekly info-availability)

Notebook `attach_last_known_weekly` (Cell 16) computes eligibility as `WeekEnd < DailyDate`
(strict). Combined with a `W-FRI` resample, this means a Friday's own just-closed weekly candle
is **not** usable on a Friday EOD scan — only from the following Monday. The refactor brief
(Section 9) explicitly calls the notebook's rule "more conservative than necessary" and requires
an explicit `data_available_timestamp <= signal_timestamp` model, where a completed session's EOD
data is available from that same session's close onward. This is the **one place** where the
refactor changes evaluated output versus the notebook for a specific date (Friday itself); it is
documented here, in `STRATEGY_SPEC.md`, and covered by a dedicated regression test
(`tests/lookahead/test_weekly_availability.py`) that pins both the old and new behavior so the
change is visible, not silent. Everything else in the weekly engine (which sessions belong to
which week, the OHLC aggregation itself, the EMA math) is unchanged.

Additionally, `build_true_weekly_ohlc` groups by a fixed `W-FRI` pandas anchor, which the brief
(Section 9) flags as unsafe for special/irregular sessions (e.g. a Saturday Muhurat session would
either be silently dropped or misfiled into the wrong ISO week by a naive `W-FRI` resample). The
refactor groups by the **actual NSE trading-calendar week** (ISO year/week of real trading
sessions present in the data) instead of a fixed weekday anchor, which is mathematically
equivalent to `W-FRI` in an ordinary Mon–Fri week but behaves correctly around holidays and
special sessions. This is a calendar-correctness fix, not a strategy-logic change.

## 4. Bugs found and fixed (behavior-preserving unless noted)

| Bug | Where | Why it matters | Fix |
|---|---|---|---|
| `MAX_STALE_DAYS = 5` in `Config`, but `run_full_universe_pipeline` calls `validate_ohlc(..., max_stale_days=10_000, ...)` | Cell 36 | The configured staleness threshold is **never actually enforced** in the live pipeline — silently defeats Section 20 of the brief even inside the original notebook. | `data/quality.py` now takes the threshold from config, and the pipeline no longer overrides it with a giant literal. Staleness is also computed in **trading sessions**, not calendar days (see below). |
| Staleness measured in calendar days (`(now - last_date).days`) | Cell 12 | Friday→Monday looks "3 days stale" even with zero missed sessions; a holiday makes it worse. | `data/quality.py` computes `sessions_since_last_valid_bar` from the NSE calendar. |
| `start_date = (pd.Timestamp.today() - DateOffset(...))`, and "latest row" for the live scan is just `feats.index.max()` | Cell 36 | Directly depends on wall-clock `today()` with no check that the current session has actually completed — exactly the failure mode Section 11 of the brief warns about (weekends, holidays, pre-close runs). | `calendar/sessions.py::resolve_analysis_date()` — automatic mode now resolves the latest **completed** NSE session using session close time in `Asia/Kolkata`, not `today()`. |
| `resample("W-FRI")` for weekly grouping | Cell 16 | See §3. | Calendar-aware ISO-week grouping. |
| Hard-coded `60` in `classify_pullback`'s `ever_broke_out` rolling window | Cell 26 | Magic number, not in `Config`, so Section 63 of the brief is technically violated even though every *other* threshold in the same cell is parameterized. | Promoted to `PULLBACK_BREAKOUT_MEMORY_BARS` in config, default value unchanged (60), so output is identical unless a user changes it. |
| yfinance `end` date is exclusive; notebook's `get_daily_ohlc` passes `end` straight through | Cell 10 | Section 15 of the brief specifically warns about this; unverified whether the notebook's requested final date is actually included. | `data/yfinance.py` adds one calendar day internally before calling the API and documents why, with a dedicated test (`tests/unit/test_yfinance_provider.py::test_end_date_is_inclusive`) using a fake HTTP layer (no live network call in CI). |
| `Volume_Ratio`/"dollar turnover" naming | Cell 36 | Brief Section 35: use INR terminology, not "dollar turnover", for an NSE system. | Renamed to `Average_Daily_Traded_Value` in the new liquidity module; the stored numbers are unchanged, only the label. |

No formula, threshold value, or trading rule was changed as part of a "bug fix" above except the
weekly-availability boundary condition described in §3, which the brief explicitly instructed be
fixed and which is called out on its own.

## 5. Where the refactor adds genuinely new code (not present in the notebook at all)

The brief (Sections 46–51) asks for capabilities the notebook does not implement:

1. **Stateful portfolio backtest** (`research/backtest.py`) — the notebook only ever computes an
   *event study* (forward returns from a point, no state, no capital, no concurrent-position
   accounting). A real backtest engine with cash/positions/trade log/equity curve did not exist
   before this refactor. This is new code, built to the brief's Section 49 spec, and is labeled
   `ENGINEERING_DECISION` throughout its docstrings. It has not been validated against real
   market data in this environment (see `RESEARCH_LIMITATIONS.md` — no live network access here).
2. **True walk-forward parameter search (Mode 2)** (`research/walk_forward.py::true_walk_forward`)
   — freezes an EMA-period combination selected on each fold's *training* window, then evaluates
   it, untouched, on that fold's *test* window. The notebook's Mode 3 is Mode-1-only (fixed spec).
   Mode 2 is new, deliberately simple (grid search on training-window median return only), and
   documented as such — it is not a sophisticated optimizer.
3. **NSE trading calendar as a first-class module** (`calendar/`) — the notebook never handles
   holidays explicitly at all (it just uses whatever dates yfinance returns). Built on top of the
   real `pandas_market_calendars` `XNSE` calendar (verified installable from PyPI, see
   `DATA_SOURCES.md`), with an explicit override hook for special sessions the library may not
   capture correctly (e.g. Muhurat trading), because Section 10 of the brief specifically warns
   against treating a packaged calendar as an unquestioned source of truth.
4. **Bootstrap confidence intervals** (`research/statistics.py::block_bootstrap_ci`) — the
   notebook reports only point estimates. New code per Section 54.
5. **CLI, typed config, run manifest, structured logging, provider abstraction layers** — pure
   engineering scaffolding around the preserved research logic; no strategy semantics live here.

Every one of these is additive scaffolding or a genuinely new research capability the brief asked
for — none of them changes the math of EMA/alignment/crossover/cluster/entries/pullback/stops
inherited from the notebook.
