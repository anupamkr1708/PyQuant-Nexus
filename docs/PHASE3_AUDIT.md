# Phase 3 Audit — Second Adversarial Review Response

Classification per item: **PRESERVED / BUG FIX / ENGINEERING CHANGE /
RESEARCH HYPOTHESIS / NOT IMPLEMENTED**. No architecture rewrite — every fix
is inside the existing module boundaries from Phase 1/2.

## 1. Point-in-time corporate-action handling — **BUG FIX**
`data/corporate_actions.py::point_in_time_split_adjustment` masks split events
dated after `as_of_date` before computing the back-adjustment factor.
`data/normalization.py` threads `as_of_date` through. 3 tests in
`tests/lookahead/test_point_in_time_corporate_actions.py`, including a
negative control proving the pre-fix path genuinely leaks.

## 2. Raw-data-preserving cache — **BUG FIX**
`data/cache.py` now stores RAW provider columns (`Dividends`/`Stock
Splits`/`AdjClose` included); normalization happens fresh in
`data/repository.py` at read time using the caller's own `end_date` as
`as_of_date`. This is what makes fix #1 actually work across a growing cache.

## 3. `same_close` backtest execution — **BUG FIX (severe)**
Confirmed and fixed a real bug: `same_close` orders were created in the
"new signals" step, one step AFTER the "execute pending orders due today"
step had already run for that date — they could never execute on any later
date either. `same_close` now executes immediately, bypassing the pending
queue entirely. `tests/regression/test_same_close_execution.py` uses a
deterministic (non-random) fixture and a sanity check that reintroducing the
bug makes the test fail.

## 4/5. Event study execution-relative horizons + MFE/MAE — **BUG FIX**
`research/event_study.py` now anchors every horizon and MFE/MAE window on
`Execution_Date`'s row position, with session-stage-aware offsets (`OPEN`
stage: H=1 = same-session close; `CLOSE` stage: H=1 = following session's
close). 6 deterministic regression tests, 3 of which were confirmed to fail
when the old signal-date-anchored logic is reintroduced.

## 6. Walk-forward Mode 2 warmup — **BUG FIX**
`true_walk_forward` now builds features from `[warmup_start, fold_end)` per
fold (via `calculate_required_warmup`) and trims to the fold's own window
only afterward, instead of slicing raw OHLCV at the fold boundary before any
indicator exists. 2 tests, including a signal-level continuity check.

## 7. Benchmark resolver — **BUG FIX**
`features/regime.py::resolve_benchmark` is the one place a benchmark ticker
is decided. NIFTY50→`^NSEI` (verified). NIFTY200 is **NOT** resolved to a
guessed ticker — a web search found no confirmed Yahoo Finance symbol, so it
raises a clear, actionable error rather than inventing one (CUSTOM +
explicit symbol is the escape hatch). Configured `index_ema_*` periods are
now actually passed to `compute_market_regime` everywhere it's called
(`cli.py`, `research/sensitivity.py`, `research/walk_forward.py`). 6 tests.

## 8. Special-session / Muhurat calendar — **NEW (ENGINEERING_DECISION)**
`calendar/reference.py` + `configs/nse_special_sessions.yaml`: a
`CalendarReferenceEntry` model that refuses to accept a time unless
`timing_verified=True`. The 2026 Muhurat DATE (Sun 8 Nov 2026) is populated
from secondary sources citing NSE's own 2026 holiday list; its TIMING is left
`null` — deliberately not inferred. `NSECalendar.expected_week_ends` makes
weekly-boundary logic use the CALENDAR's scheduled last session of a week,
not just whichever bar happens to be present — the Friday→Sunday-Muhurat
scenario is directly tested. Also fixed a real bug found while building this:
`valid_sessions` was injecting override dates regardless of the requested
range. 11 + 1 tests.

## 9/10. Non-finite OHLCV rejection + index contract — **BUG FIX**
`data/quality.py` explicitly checks for NaN/±inf (a numeric-dtype check alone
doesn't catch these) and enforces `DatetimeIndex`, tz-naive, midnight-
normalized — never merely assumed from a provider. 7 tests.

## 11. Internal cache gaps (RANGE_COVERED vs RANGE_COMPLETE) — **BUG FIX**
`data/repository.py` now runs a gap-check against the exchange calendar even
on a cache hit; `RefreshDiagnostics.internal_gap_sessions` / `range_complete`
surface real holes. 3 tests, including the exact Jan 1,2,3,[missing 4],5
fixture requested.

## 12. Cache versioning — **BUG FIX**
`RAW_CACHE_SCHEMA_VERSION` gates `DataCache.read()` — a stale/missing schema
version is treated as a cache MISS, forcing a clean refetch. 2 tests.

## 13. Composite provider provenance — **BUG FIX**
`RefreshDiagnostics.resolved_source` records the concrete provider that
actually served each fetch, never the string `"composite"`. 1 dedicated test.

## 14. Next session date vs. price — **BUG FIX**
`reporting/scanner.py`: `Next_Session_Date` is now resolved directly from
`calendar.next_session()` (a pure calendar fact), independent of whether
`Execution_Reference` (the price) is available — v1 set both to `None`
together, incorrectly implying the date was also unknown. 3 tests.

## 15. Position sizing basis — **BUG FIX**
Confirmed a real discrepancy from STRATEGY_SPEC.md's own documented formula:
the backtest was sizing off raw `cash`, not `equity`. `risk_budget_basis`
(config, default `EQUITY`) now matches the spec; `CASH` is available as an
explicit, non-default research variant. Affordability is still always
cash-constrained regardless of sizing basis. 2 tests.

## 16. Same-day exit/stop handling — **BUG FIX**
Exits are no longer unconditionally skipped on `d == execution_date`. An
`OPEN`-stage fill (next_open) is eligible for a same-day stop hit via a plain
`Low <= stop` check (no gap-through logic, since the entry price itself was
already validated against the stop). `CLOSE`-stage fills correctly have no
same-day exit (no price path remains that session). 1 dedicated deterministic
test plus coverage in the timeline tests.

## 17. Entry-day MFE/MAE — **BUG FIX**
MFE/MAE tracking starts on the entry day itself for `OPEN`-stage fills,
and only from the following session for `CLOSE`-stage fills. Also fixed in
the event-study engine (#5). 1 dedicated test with a large same-day High
spike as the discriminator.

## 18. Portfolio turnover — **BUG FIX (naming)**
`turnover_trades_per_year` (which was actually just a trade-count rate) is
now `trade_frequency_per_year`; a genuine notional turnover
(`sum(|entry_price*qty|)/avg equity`) is reported separately as
`notional_turnover_pct`. 1 deterministic test proving the two are numerically
distinct.

## 19. Portfolio statistics formulas — **BUG FIX / ENGINEERING CHANGE**
CAGR uses exact elapsed calendar days, not a session-count approximation.
Sharpe takes an explicit (documented, default-0.0) `risk_free_rate_annual`.
Sortino's downside deviation is relative to an explicit `mar_annual`
threshold, not simply "returns below zero". 7 deterministic fixture tests
with hand-computed expected values (e.g. exact-100%-CAGR-over-365-days,
exact-25%-drawdown, exact-3-session drawdown duration).

## 20. Cross-sectional (date) clustering — **NEW (RESEARCH_HYPOTHESIS, explicitly not rigorous)**
`block_bootstrap_ci_by_date` and `two_way_cluster_bootstrap_ci` added
alongside the existing ticker-clustered bootstrap. The two-way version is
explicitly documented as an approximation (intersecting independently
resampled ticker/date index sets), NOT a rigorous multi-way cluster-robust
estimator — it reports both single-way CIs and a combined widest bound so a
reader isn't misled. 4 tests, including one proving ticker-only clustering
measurably understates uncertainty on data with a shared date-level shock.

## 21. Test quality audit — **BUG FIX (test-only)**
Found and fixed one genuinely vacuous assertion
(`assert x != y or True`, always true) in the Phase-2 manifest test. Found
and strengthened one weak-but-not-wrong pattern (`len(signals) <=
len(universe)`, trivially true by construction) into a test that forces a
guaranteed non-triggering row and asserts it's excluded. Added a "reintroduce
the bug, confirm the test fails" sanity check for both the `same_close` fix
and the event-study execution-relative fix. No test was found with zero
assertions that wasn't a legitimate `pytest.raises(...)` context manager.

## 22. RS percentile test strength — **BUG FIX (test-only)**
Replaced the single-symbol test with a 3-symbol (AAA/BBB/CCC) fixture with a
known ranking, extreme future-value injection proving exact invariance, AND
a negative control proving the same injected values DO change the ranking
when read at a non-future date (so the invariance isn't vacuously true).

## 23. Warmup signal invariance — **BUG FIX (test-only)**
Replaced the `<1%` numeric-tolerance check with exact equality checks on
every discrete/categorical signal-level column (`Daily_State`,
`Any_Entry_Triggered`, all six crossover columns, etc.) across 20 spot-check
dates spanning the evaluation window, not just one lucky date.

## 24. yfinance `repair` semantics — **BUG FIX**
Changed `repair=True` → `repair=False` (the review's explicit preference,
since repaired observations weren't being separately captured/audited).
`ProviderMetadata.vendor_repair_enabled` and the raw-cache metadata sidecar
now record the choice so it's never a hidden preprocessing step. 1 test.

## 25. No-magic-numbers audit — **BUG FIX**
Found and promoted four previously-buried constants to config:
`cluster.width_slope_lookback_days` (was a bare `.rolling(5)`),
`cluster.percentile_min_periods` (was a bare `min_periods=30` × 2),
`volatility.ema_slope_lookback_days` (was a bare `k=10` default),
`liquidity.volume_window_fast/slow_days` (were bare function defaults never
reachable from config). All wired through `signal_engine.py`. 3 tests proving
each actually changes computed output when changed (not merely present and
ignored). **NOT_IMPLEMENTED**: an exhaustive line-by-line audit of every
numeric literal in the codebase (e.g. the `0.30` single-day-gap threshold in
quality.py, the `1e-9` epsilon comparisons) — the ones found and fixed were
the ones with genuine research significance; small numerical-stability
epsilons were left as implementation detail, not promoted to config.

## 26. Config propagation — **BUG FIX (partial) / verified**
Direct tests now prove `research.backtest.*`, `strategy.regime.benchmark`,
`strategy.cluster.width_slope_lookback_days`,
`strategy.volatility.ema_slope_lookback_days`, and
`strategy.liquidity.volume_window_fast_days` all actually reach computed
output. `research.horizons_days`, `execution.model`, and cost-scenario
propagation were already exercised indirectly by existing Phase-1/2 tests.
**NOT_IMPLEMENTED**: a single exhaustive propagation test enumerating every
config field automatically (would need a generic "does changing field X
change output Y" harness) — done selectively for the fields with the
clearest research impact instead, to avoid overengineering a meta-test
framework.

## 27. Research data completeness — **BUG FIX**
`research/data_audit.py::build_research_data_audit` replaces the bare
`except: continue` in `_load_universe_frames` with an explicit per-symbol
exclusion reason (`data_fetch`, `quality_gate`, `pipeline`, or "no rows after
trim"). `event-study`/`backtest`/`walk-forward --mode 1` now print
`audit.summary_line()` and write `research_data_audit.csv`. 3 tests.

## 28. Real-data smoke test — **NOT PERFORMED**
Same environment constraint as Phase 1/2: this sandbox cannot reach
yfinance/NSE. `tests/integration/test_live_data.py` (gated by
`EMA_SCANNER_LIVE=1`) correctly skips rather than fails here.

## 29. Real historical study (2015–2026, all entry models) — **NOT PERFORMED**
Blocked on #28 by design (the brief explicitly says not to run this until
the blockers pass) and by the same no-network constraint.

## 30. Final acceptance standard — see the final report's Section M
(test results) and Section O (remaining limitations) for the complete,
honest checklist against every item this section lists.
