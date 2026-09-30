# Changelog

## 0.3.0 -- Phase 3: second adversarial correctness audit response

Full itemized response in `docs/PHASE3_AUDIT.md`. Headline fixes:

- **same_close signals never executed** (severe bug) -- fixed by giving
  same_close an immediate-execution path instead of routing through the
  pending-order queue.
- **Point-in-time corporate-action leakage** -- split back-adjustment now
  masks any split dated after the decision date; the cache now stores RAW
  data (not pre-adjusted) so this stays correct as the cache grows.
- **Event study was signal-date-relative, not execution-date-relative** --
  every horizon and MFE/MAE window now anchors on the actual execution date
  with session-stage-aware offsets.
- Position sizing now uses EQUITY (matching STRATEGY_SPEC.md), not cash.
- Same-day stop exits and entry-day MFE/MAE now correctly handled for
  next_open fills.
- Non-finite (NaN/inf) OHLCV and index-contract violations are now hard
  quality failures.
- Internal cache gaps (RANGE_COVERED vs RANGE_COMPLETE) are now detected.
- Cache versioning, composite-provider provenance, and yfinance `repair=`
  choice are all now recorded/auditable.
- Benchmark configuration (NIFTY50/NIFTY200/CUSTOM) now actually resolves to
  a real ticker (or fails clearly rather than guessing one) and configured
  regime EMA periods actually reach `compute_market_regime`.
- Special-session (Muhurat) calendar reference data model added, distinguishing
  known trading DATE from known session TIMING -- no time is ever inferred.
- Walk-forward Mode 2 now builds features with proper per-fold warmup.
- Portfolio statistics: turnover renamed/fixed (trade-count vs. true notional
  turnover), CAGR/Sharpe/Sortino formulas made explicit with deterministic
  fixture tests, date-clustered and two-way bootstrap CIs added.
- Several Phase-2 tests strengthened after a vacuous-assertion audit (one
  genuinely vacuous `... or True` assertion found and fixed).
- Four previously-buried magic numbers promoted to config.
- Research commands no longer silently skip excluded symbols -- an explicit
  data-completeness audit report is now produced.

See docs/PHASE3_AUDIT.md for the full section-by-section classification.

## 0.2.0 -- Phase 2: adversarial correctness review response

Full itemized response in `docs/PHASE2_AUDIT.md`. No architecture rewrite --
targeted fixes inside the existing module boundaries. Headline BUG FIXES:

- Price semantics: SPLIT_ADJUSTED no longer derived from AdjClose/Close
  (dividend-contaminated); pure split-only back-adjustment implemented.
- Cache-first data flow: CLI no longer re-downloads full history every run.
- Provider factory: config's primary/secondary_provider now actually control
  what gets instantiated (previously ignored by CLI commands).
- Manual-date safety: today-before-cutoff rejected, future dates always
  rejected, distinct exchange-close vs. EOD-data-cutoff concepts.
- Analysis-date data gate: a missing bar for the resolved date is now a hard
  DATA_MISSING_ANALYSIS_SESSION failure, never a silent fallback to the
  previous bar.
- Warm-up engine: research/backtest commands now fetch sufficient prior
  history before the requested evaluation window.
- Cross-sectional RS percentile: actually computed now (was always None).
- Backtest execution timeline: signals create a PENDING_ORDER with no cash/
  exposure impact until the actual execution date (previously leaked future
  exposure into a past valuation).
- Positional execution fallback removed: a missing calendar-resolved session
  is now a DATA_GAP, never silently advanced to "the next row".
- Stop/entry geometry validated explicitly (INVALID_RISK_GEOMETRY) rather than
  hidden behind abs(entry-stop).
- Event-study statistics vs. portfolio statistics are now fully separate;
  event-level "max drawdown" (meaningless for non-chronological, overlapping
  observations) was removed.
- Scanner output split into universe_diagnostics / candidates / signals;
  "signals_found" now means actual entry triggers, not processed-symbol count.
- Manifest schema corrected to the exact required field set.

See docs/PHASE2_AUDIT.md for the full section-by-section classification
(PRESERVED / BUG FIX / ENGINEERING CHANGE / RESEARCH HYPOTHESIS / NOT
IMPLEMENTED) of every item in the Phase-2 review.

## 0.1.0 — Initial refactor (2026-09-23)

Refactor of `Nifty200_EMA_Cluster_Research.ipynb` into `ema_scanner`. See
`docs/NOTEBOOK_AUDIT.md` for the full traceability matrix.

**Strategy math**: unchanged (EMA recursion/seed, alignment, crossovers,
Definitions A-D, Entry models A-E, swing confirmation, pullback bands, ATR,
regime, relative strength) — `STRATEGY_VERSION = "ema_cluster_v1"`.

**Behavior changes** (both documented in `NOTEBOOK_AUDIT.md §3-4`, both
covered by regression tests):
- Weekly-candle availability boundary changed from strict `<` to non-strict
  `<=` — a Friday's own just-closed weekly candle is now usable on a Friday
  EOD scan (previously required waiting until Monday).
- Weekly grouping changed from a fixed `resample("W-FRI")` anchor to
  calendar-aware ISO-week grouping (equivalent in an ordinary week; differs
  around holidays/special sessions).
- Data staleness now measured in trading sessions (via the real NSE calendar)
  instead of calendar days, and the configured `max_stale_sessions` threshold
  is now actually enforced (previously silently overridden with a very large
  literal in the live pipeline).
- `pullback.breakout_memory_bars` (previously an unlabeled `60` inside a
  function body) is now a named, configurable parameter — default value
  unchanged.
- Liquidity diagnostic renamed `Volume_Ratio`'s companion metric from "dollar
  turnover" naming to `Average_Daily_Traded_Value` (INR terminology) — values
  unchanged.

**New capabilities** (not present in the notebook at all — all labeled
`ENGINEERING_DECISION` in their module docstrings, none validated against
real market data yet — see `docs/RESEARCH_LIMITATIONS.md`):
- `research/backtest.py` — stateful portfolio backtest engine (cash,
  positions, stops with gap modeling, trade log, equity curve).
- `research/walk_forward.py::true_walk_forward` — Mode 2 nested train/test
  parameter search (Mode 1, the notebook's fixed-spec rolling OOS evaluation,
  is preserved as-is).
- `research/statistics.py::block_bootstrap_ci` — cluster-bootstrap confidence
  intervals.
- `calendar/` — NSE trading calendar and point-in-time analysis-date
  resolution (the notebook had neither; it used whatever dates the data
  provider returned).
- `data/base.py`, `data/cache.py`, `data/quality.py` (extended),
  `data/normalization.py`, `data/nse.py` (interface only, unverified
  endpoint), `universe/historical.py` (interface only) — provider/cache/
  universe scaffolding per the refactor brief's architecture requirements.
- Typed configuration (`config.py`, `configs/default.yaml`) replacing the
  notebook's single mutable `Config` class.
- CLI (`cli.py`): `scan`, `backtest`, `event-study`, `walk-forward`,
  `sensitivity`, `validate-data`, `show-config`.
