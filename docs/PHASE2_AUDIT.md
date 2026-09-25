# Phase 2 Audit — Adversarial Review Response

This document records the response to the Phase-2 adversarial Principal Quant
Engineer review. Per that review's instruction, **the architecture from
Version 1 was NOT rewritten** — every fix below is a targeted change inside
the existing module boundaries (`docs/ARCHITECTURE.md` is still accurate).

Classification per change, as requested: **PRESERVED / BUG FIX / ENGINEERING
CHANGE / RESEARCH HYPOTHESIS / NOT IMPLEMENTED**.

## Section 1 — Price semantics (BLOCKER) — **BUG FIX**

`data/normalization.py`'s `SPLIT_ADJUSTED` mode previously computed a
"split factor" as `AdjClose/Close`, which mixes in dividends. Rewrote
`data/corporate_actions.py` to derive a pure split-only back-adjustment
factor from the `Stock Splits` column (standard back-adjustment algorithm —
see that module's docstring for the exact recursion). `TOTAL_RETURN_SERIES`
now exposes `AdjClose` under its correct name via `total_return_close()`,
kept fully separate from the OHLCV basis fed to EMA/ATR/swings/stops.
`TOTAL_RETURN_ADJUSTED` as an *OHLCV basis* raises `NotImplementedError`
rather than fabricating Open/High/Low that Yahoo doesn't publish. Regression
tests in `tests/regression/test_corporate_actions.py` (7 tests) construct a
fixture with both a split and a dividend and prove RAW/SPLIT_ADJUSTED/
TOTAL_RETURN diverge exactly as they should, and specifically that
SPLIT_ADJUSTED no longer moves on a dividend-only day.

`EXECUTION_OHLCV` = `SPLIT_ADJUSTED_OHLCV` by **ENGINEERING_DECISION**
(documented in `data/normalization.py`): using raw prices for execution while
signals/stops use split-adjusted prices would create quantity/price
mismatches across a split boundary.

## Section 2 — Cache-first architecture (BLOCKER) — **BUG FIX**

New `data/repository.py::DataRepository` — cache-first flow (inspect cache →
determine missing range → fetch missing + overlap → normalize → merge →
persist). `cli.py` now uses `DataRepository` everywhere data is fetched
(`scan`, `_load_universe_frames` shared by backtest/event-study/walk-forward/
sensitivity). `RefreshDiagnostics` exposes `cache_hit`, `cache_miss`,
`refresh_start/end`, `overlap_sessions`, `previous_latest_session`,
`new_latest_session`, `rows_downloaded` — `rows_downloaded_total` is summed
into the run manifest instead of being a proxy for symbol count. 4 tests in
`tests/unit/test_data_repository.py` prove a warm cache triggers **zero**
additional provider calls for an already-covered range, and that extending
the end date only re-fetches the missing tail + overlap, not the full range.

## Section 3 — Provider factory (BLOCKER) — **BUG FIX**

New `data/factory.py::build_data_provider(cfg.data)`. Every CLI command
(`scan`, `validate_data`, `cross_check_data`, `_load_universe_frames`, and
the walk-forward/sensitivity commands) now calls this instead of
constructing `YFinanceProvider()` directly. 3 tests in
`tests/unit/test_provider_factory.py` prove changing
`primary_provider`/`secondary_provider` in config actually changes the
instantiated provider graph, and that requesting the same provider for both
slots doesn't duplicate it.

## Section 4 — Real NSE/Yahoo provider semantics — **PRESERVED / ENGINEERING CHANGE**

NSE endpoint remains unconfigured (unchanged decision — still correct per the
reviewer's own Section 19 agreement). `docs/DATA_SOURCES.md`'s verification
log is unchanged from v1 (already documented what was/wasn't verified).
yfinance parameters were already explicit in v1 (`auto_adjust=False,
actions=True, repair=True, threads=False`, exclusive-`end` compensation) —
no change needed here; `tests/unit/test_yfinance_provider.py::test_end_date_is_inclusive`
already covers the required regression.

## Section 5 — Manual date safety (BLOCKER) — **BUG FIX**

Rewrote `calendar/sessions.py::resolve_analysis_date`: `manual_date > today`
always rejected; `manual_date == today` requires `eod_data_cutoff` to have
passed; `manual_date < today` accepted if it's a real trading session (data
existence checked separately by the analysis-date data gate, Section 6). 8
new/rewritten tests in `tests/unit/test_analysis_date.py` cover exactly the
required matrix: today-before-cutoff (reject), today-after-cutoff (accept),
yesterday, future date, holiday, weekend, plus a custom-cutoff override test.

## Section 6 — Analysis-date data gate (BLOCKER) — **BUG FIX**

`data/quality.py::QualityReport` gained `eligible_for_signal` and
`analysis_date_bar_present` fields. When `as_of_date` (the resolved analysis
date) has no actual bar in the series, this is now a hard
`DATA_MISSING_ANALYSIS_SESSION` condition — `eligible_for_signal=False`. The
`scan` command in `cli.py` checks this explicitly per symbol (recording a
structured `SymbolFailure("analysis_date_gate", ...)`, not a silent
`continue`) and aborts the whole run (`ABORT_BENCHMARK`) if the *benchmark*
index is missing the analysis-date bar. 5 new tests in
`tests/unit/test_quality.py`.

## Section 7 — EOD/NSE session semantics (BLOCKER) — **ENGINEERING CHANGE**

`calendar/sessions.py` now models three distinct concepts explicitly:
`exchange_session_complete` (pure calendar fact, session close 15:30 IST),
`eod_data_cutoff_passed` (configurable, default 16:00 IST — an
**ENGINEERING_DECISION** buffer, not an exchange fact), and
`provider_data_final` (deliberately NOT decided by this module — left to the
downstream analysis-date data gate in Section 6). `configs/default.yaml` adds
`calendar.eod_data_cutoff`. **NOT_IMPLEMENTED**: precise modeling of NSE's
closing-auction / post-close mechanics per security — documented as a gap in
`docs/RESEARCH_LIMITATIONS.md`, not silently assumed away.

## Section 8 — Weekly information availability — **PRESERVED**, tests extended

The `<=` (non-strict) availability boundary from the v1 fix is unchanged
(the reviewer's own Section 22 in the Phase-1 review area agreed this should
be kept). Added 2 new tests for a holiday-shortened week (one weekday
removed from a week) proving `WeekEnd` correctly becomes the last
*actually-present* session, not an assumed Friday, and that mid-week days
still can't see that week's own forming candle.

## Section 9 — Warm-up engine (BLOCKER) — **NEW (ENGINEERING_DECISION)**

New `research/warmup.py::WarmupPolicy` / `calculate_required_warmup(cfg)`.
Heuristic (documented as such, not a rigorous derivation): `max` across
daily-EMA-long×3, weekly-EMA-long-in-daily-sessions (period×5×3, since
weekly EMA200 genuinely needs ~600 weeks of calendar time to fully converge —
see the module docstring), cluster lookback+buffer, swing confirmation×4,
ATR×5, RS-max-window×2, pullback breakout memory — plus a flat +50 buffer.
`cli.py`'s `scan` and `_load_universe_frames` both fetch
`warmup_start_via_calendar(...)` extra history and only evaluate/report the
requested window. 2 tests in `tests/lookahead/test_warmup_invariance.py`
prove that once the policy minimum is met, adding 200 more days of warmup
changes evaluation-window EMA200/cluster-width/ATR by <1% (numerical
convergence, not exact equality — EMA never becomes exactly seed-independent).

## Section 10 — Cross-sectional RS percentile (BLOCKER) — **BUG FIX**

`features/relative_strength.py::compute_universe_rs_percentile(feature_frames, analysis_date)`
assembles a same-date cross-section across the eligible universe and ranks it
— never a different date per symbol, never a future date. Wired into
`cli.py`'s `scan` command: computed once after the per-symbol loop, injected
into each row's `RS_Percentile` field (previously always `None`). 4 tests in
`tests/unit/test_rs_percentile.py`.

## Section 11 — Backtest execution state machine (BLOCKER) — **BUG FIX**

Rewrote `research/backtest.py` with an explicit `SIGNAL → PENDING_ORDER →
EXECUTED → OPEN_POSITION → EXIT → CLOSED` state machine. A signal now creates
a `_PendingOrder` with **no cash debit and no position value** until its
`execution_date` arrives in the main date loop. 4 tests in
`tests/lookahead/test_backtest_execution_timeline.py`, including a direct
check that `pending_orders` is nonzero on the signal date and `same_close`
has no pending period at all.

## Section 12 — Remove positional execution fallback (BLOCKER) — **BUG FIX**

`execution/execution_models.py::resolve_execution_price` no longer falls back
to "the next dataframe row" when the calendar's `next_session` isn't in the
data — it returns `status="DATA_GAP"`, `execution_price=None`. The backtest
engine drops such signals into `SkippedSignal(reason="data_gap")` rather than
silently executing. Covered by
`test_data_gap_execution_drops_the_signal_rather_than_faking_a_fill`.

## Section 13 — Stop/entry geometry (BLOCKER) — **BUG FIX**

`execution/sizing.py::position_size` now validates `stop < entry` (LONG) /
`stop > entry` (SHORT) **before** any distance math, returning
`reason="invalid_risk_geometry"` rather than silently proceeding via
`abs(entry-stop)`. New standalone `validate_risk_geometry()` used both in the
backtest engine (before opening any pending order) and in the scanner output
(`Risk_Geometry_Valid` column). 5 new/updated tests in
`tests/unit/test_sizing_and_costs.py`.

## Section 14 — Backtest configuration — **ENGINEERING CHANGE**

New `config.BacktestConfig` (`research.backtest` in YAML):
`initial_capital`, `max_concurrent_positions`, `max_position_pct_of_equity`,
`fixed_horizon_days`, `minimum_trade_qty`, `exit_rule`, `entry_model_col`,
`cost_scenario`. `run_portfolio_backtest`'s parameters all default from this
config object now rather than from hard-coded function-signature defaults.

## Section 15 — Event study vs. portfolio statistics (BLOCKER) — **BUG FIX**

`research/statistics.py::performance_stats` (EVENT_STUDY_STATS) **no longer
computes a drawdown at all** — it was previously derived from
`cumprod(1+r)` over non-chronological, overlapping event returns, which the
reviewer correctly identified as not a meaningful portfolio metric. New
`portfolio_stats_from_equity_curve()` (PORTFOLIO_STATS) computes CAGR,
annualized volatility, Sharpe, Sortino, Calmar, max drawdown, max drawdown
duration, average exposure, and (from the trade log) profit factor/
expectancy/turnover — from the actual time-ordered equity curve the backtest
engine produces. `BacktestResult.portfolio_stats()` is the entry point.
`research/event_study.py::comparison_table` no longer emits a
`Max_Drawdown_Pct` column at all.

## Section 16 — Overlapping-event statistics — **PRESERVED**

`research/statistics.py::block_bootstrap_ci` (same-symbol clustering) is
unchanged from v1. **NOT_IMPLEMENTED**: same-date cross-sectional clustering
(many stocks signaling on one market-wide day) — documented as a limitation,
not addressed in this pass (would need a second, more involved clustering
dimension; out of scope to avoid overengineering an already-first-pass
inference procedure further).

## Section 17 — Transaction cost model — **ENGINEERING CHANGE**

`execution/costs.py` is now side-aware: `compute_transaction_cost_pct(...,
side="buy"|"sell")` and `compute_round_trip_cost_pct(...)` (buy-leg + sell-leg,
replacing the old `2 × one_leg_cost_pct` symmetric assumption).
`CostsConfig` gained `stt_buy_pct`/`stt_sell_pct` overrides and
`stamp_duty_buy_only`. Added a `stress_cost` scenario (3×) alongside
zero/low/base/high. **NOT_IMPLEMENTED** (explicitly, to avoid
overengineering unverified numbers): a full `BrokerProfile`/`ProductType`
(delivery vs. intraday, broker-specific slabs) hierarchy — documented in
`configs/default.yaml`'s comments as out of scope for this pass.

## Section 18 — Scanner output semantics (BLOCKER) — **BUG FIX**

`reporting/scanner.py::build_scanner_tables()` now returns FOUR distinct
datasets (`universe_diagnostics`, `candidates`, `signals`); `len(signals)` is
the only correct meaning of "signals found" (previously the CLI counted
every successfully-processed row). `Signal_Close` replaced the old
`Suggested_Entry_Reference` label; `Execution_Model`/`Next_Session_Date`/
`Execution_Reference` are separate, explicit fields, with
`Execution_Reference` populated only from a real resolved next-session bar
(never fabricated). 3 tests in `tests/unit/test_scanner_output.py`.

## Section 19 — Entry-model isolation — **PRESERVED**

Already satisfied in v1 (`strategy/entries.py` keeps A–E fully independent;
`Entry_Models_Triggered` lists ALL triggering models, not just one). No
change needed; re-verified during this review.

## Section 20 — Swing stop audit — **NEW (ENGINEERING_DECISION)**

`features/swing.py::vectorized_last_confirmed_swing_low_audit()` — new
companion function producing `Swing_Low_Source_Date` /
`Swing_Low_Available_Date` alongside the existing forward-filled stop price.
`execution/stops.py` attaches these as `Confirmed_Swing_Low_Date` /
`Confirmed_Swing_Low_Available_Date`. `Trade` (models.py) gained
`stop_source_swing_date` / `stop_available_date` fields, populated by
`research/backtest.py` from the pending order's stored audit trail.

## Section 21 — Current vs. historical universe — **PRESERVED**

`UNIVERSE_MODE` labeling unchanged (`CURRENT_NIFTY200_HISTORICAL_SIMULATION`
by default; `universe/historical.py`'s `PointInTimeUniverseProvider`
interface unchanged). No change needed.

## Section 22 — Manifest correctness (BLOCKER) — **BUG FIX**

`models.RunManifest` rewritten to the exact field list requested:
`provider` (not `data_provider`), `data_quality_counts` (not
`data_quality_summary`), plus newly-added `decision_timestamp`,
`universe_count`, `symbols_requested/processed/failed` (distinct from
`stale_symbols`), `git_commit`/`git_dirty` (best-effort via `git`
subprocess, `None` if not in a git repo), `rows_downloaded` now genuinely
summed from `RefreshDiagnostics.rows_downloaded` across all symbols (not a
symbol count), `missing_sessions` genuinely summed from each symbol's
`QualityReport.missing_expected_sessions` (never hard-coded `0`). Old field
names kept as optional deprecated aliases so nothing reading a v1 manifest
schema hard-crashes. 3 tests in `tests/unit/test_manifest.py`.

## Section 23 — Parameter metadata — **NEW (ENGINEERING_DECISION, deliberately lightweight)**

New `strategy/parameter_registry.py::PARAMETER_CATEGORIES` — a flat,
machine-readable dict (not a schema-validation framework, per the
instruction not to overengineer this). `show-config` now prints each
registered parameter's category at runtime. 4 tests in
`tests/unit/test_parameter_registry.py`. **NOT_IMPLEMENTED**: every single
config field is not registered (only the ones with genuine research-hygiene
significance) — extending the dict is a one-line addition per parameter if
more coverage is wanted later.

## Section 24-25 — EMA/feature invariants, quality-gate severity (BLOCKER) — **BUG FIX**

Duplicate dates and a non-monotonic index are now **hard `FAIL`** conditions
(previously WARN-level issues that didn't affect `status`). `eligible_for_signal`
is a first-class `QualityReport` field. 4 new tests in `tests/unit/test_quality.py`.
No change was made to NaN interpolation behavior (v1 never interpolated
missing OHLC bars — this was already correct and is unchanged).

## Section 26 — Corporate action regression tests — **NEW**

`tests/regression/test_corporate_actions.py` — 7 tests, described under
Section 1 above.

## Section 27 — Real-data integration test mode — **NEW**

`tests/integration/test_live_data.py`, gated by `EMA_SCANNER_LIVE=1`
(`pytest.mark.skipif` otherwise). 3 tests covering provider connectivity,
calendar resolution, and end-to-end feature generation on RELIANCE/TCS/INFY +
`^NSEI`. **Not run** in this environment (no network access here — see
`RESEARCH_LIMITATIONS.md`); correctly skips (3 skipped, not failed) in the
default test run.

## Section 28 — Real-data cross-check — **NEW**

`ema-scanner cross-check-data --symbols ... --start ... --end ...` command
added to `cli.py`, comparing primary vs. secondary provider OHLCV per field/
date, reporting percentage differences (not requiring exact equality) to
`data_crosscheck_report.csv`. Not exercised against real data (no network
here).

## Section 29 — Backtest end-of-data — **BUG FIX**

`research/backtest.py` now closes a still-open position at end-of-data using
**that symbol's own last valid Close at-or-before the backtest's end date**
(`END_OF_DATA_SYMBOL`), not `pos.entry_price`. The old fallback survives only
as an explicitly-labeled, clearly-commented last resort
(`END_OF_DATA_NO_VALID_BAR`) for the (should-not-happen) case where a symbol
with an open position somehow has zero valid bars at all.

## Section 30 — Walk-forward Mode 2 — **BUG FIX (naming)**

Output columns renamed from `selected_fast/medium/structural/long` +
`train_selection_metric` to `selected_training_fast/medium/structural/long` +
`training_window_selection_metric` + an explicit `selection_basis` string —
never called "optimal" anywhere in code, docs, or CLI output (the `walk-forward
--mode 2` command now also prints an explicit reminder). The actual
train→select→freeze→test logic and warm-up wiring were otherwise already
correct in v1 and are unchanged.

## Section 31 — Final acceptance test — see **Section M** of the final report below.

## Section 32 — No fake research results — **PRESERVED**

Unchanged policy: `tests/fixtures/synthetic.py` is imported only from
`tests/`, never from `src/ema_scanner`. No real-data research run was
performed or claimed in this pass (see Section N below).

## Section 33 — Real data smoke test — **NOT PERFORMED** (documented, not hidden)

See RESEARCH_LIMITATIONS.md and Section N of the final report: no network
access to yfinance/NSE in this build environment.
