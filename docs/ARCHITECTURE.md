# Architecture

## Two separate pipelines (brief Section 106 — do not collapse these)

```
LIVE / PRODUCTION EOD SCAN:
  exchange calendar -> point-in-time date resolution -> universe (current)
    -> raw EOD data -> quality gates -> normalization -> feature engine
    -> EMA/alignment/crossovers -> weekly context -> cluster -> swings
    -> pullback -> regime/RS/liquidity -> strategy triggers -> optional filters
    -> risk/stop -> execution reference -> signal -> reporting

RESEARCH (event study):
  historical data -> point-in-time universe (or labeled CURRENT-UNIVERSE
    HISTORICAL SIMULATION) -> feature engine (SAME code as above) -> strategy
    events -> event study (forward returns, MFE/MAE) -> statistics

RESEARCH (portfolio backtest):
  historical data -> point-in-time universe -> feature engine -> signals
    -> execution simulation -> stateful portfolio backtest -> trade log /
    equity curve
```

All three consume the identical `strategy/signal_engine.build_stock_feature_frame`
— there is exactly one feature pipeline, reused everywhere, so "what counts as
a signal" can never silently differ between the live scanner and research.

## Module map

```
calendar/     NSE trading calendar (pandas_market_calendars XNSE) + point-in-
              time analysis-date resolution. No strategy logic lives here.
universe/     Current NIFTY 200 (live fetch, fails loudly) + point-in-time
              historical universe INTERFACE (not implemented — see
              NOTEBOOK_AUDIT.md §2) + a minimal security-master stub.
data/         Provider abstraction (base.py) + yfinance (implemented, pinned,
              tested) + NSE bhavcopy (interface only — endpoint unverified,
              see DATA_SOURCES.md) + cache (atomic parquet) + quality gates +
              normalization/price-mode + corporate-actions interface.
features/     Pure, deterministic, no-network functions: ema, alignment,
              crossover, weekly, cluster, volatility, swing, pullback, regime,
              relative_strength, liquidity. Each is independently unit-tested.
strategy/     Wires features into Definitions A-D, Entry models A-E, the
              signal-state machine, the (diagnostic-only) heuristic score, and
              optional filters. signal_engine.py is the one master pipeline
              function everything else calls.
execution/    Stops, position sizing, execution-price resolution (same_close/
              next_open/next_close via the real calendar), transaction costs.
              Deliberately separate from strategy/ — sizing never changes what
              counts as a signal.
research/     event_study.py (what happened after signals — descriptive),
              backtest.py (NEW: stateful portfolio engine), walk_forward.py
              (Mode 1 ported + Mode 2 new), sensitivity.py, statistics.py
              (incl. a new block-bootstrap CI).
reporting/    scanner.py (assembles the Section-38 output table), csv.py,
              excel.py (percent-format fix preserved), manifest.py, audit.py.
cli.py        Wires all of the above into `ema-scanner scan|backtest|
              event-study|walk-forward|sensitivity|validate-data|show-config`.
```

## Design principles actually enforced (not just stated)

- **No magic numbers in function bodies.** Every strategy/research parameter
  lives in `config.py` / `configs/default.yaml` with a `category` label.
- **No global mutable state.** `Config` is a pydantic model; sensitivity/
  walk-forward code uses `cfg.model_copy(deep=True)` per trial rather than
  mutating a shared instance.
- **No hidden network calls inside feature functions.** Everything in
  `features/` takes DataFrames/Series in, returns DataFrames/Series out.
  Network access is confined to `data/` and `universe/`.
- **No synthetic data outside tests.** `tests/fixtures/synthetic.py` is
  imported only from `tests/`; nothing in `src/ema_scanner` imports it.
- **Determinism.** Same data snapshot + config + code -> identical features/
  signals/research results (apart from wall-clock metadata). `Config.
  config_hash()` and the run manifest exist specifically to make this
  checkable.
