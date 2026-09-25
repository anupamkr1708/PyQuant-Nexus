# EMA Scanner — NIFTY 200 EMA-Cluster Research & EOD Signal System

Refactor of `notebooks/Nifty200_EMA_Cluster_Research.ipynb` into a modular,
tested, reproducible Python research and EOD scanner system. The notebook is
kept unchanged in this repo as historical research provenance — it is the
source of truth for the original strategy logic; see `docs/NOTEBOOK_AUDIT.md`
for the complete traceability matrix from notebook cell to Python module.

**Read `docs/RESEARCH_LIMITATIONS.md` before using this for real decisions.**
In short: this has been built and tested for correctness (no look-ahead,
calendar-correct dates, explicit execution/cost assumptions), but it has
**not yet been run against real market data** in the environment this refactor
was built in (sandboxed, no access to Yahoo Finance / NSE), so no economic
conclusion ("this works" / "this doesn't") exists yet. That validation step is
still required before trusting any signal or research number.

## What this system does

- Scans the NIFTY 200 end-of-day for EMA-cluster setups (EMA10/20/89/200),
  using daily structure confirmed by weekly context, with five independently
  selectable entry models and four independent "cluster crossover"
  interpretations (see `docs/STRATEGY_SPEC.md`).
- Resolves the correct analysis date automatically (latest COMPLETED NSE
  session) or accepts a validated manual historical date — never guesses with
  wall-clock arithmetic.
- Runs research separately from the live scanner: event studies, a stateful
  portfolio backtest, walk-forward analysis (both a fixed-spec and a true
  nested-parameter-search mode), and parameter-robustness sensitivity grids.
- Enforces point-in-time data integrity throughout: weekly candles, swing
  confirmations, and universe membership are all availability-gated so a
  historical scan can never see future information.

## What this system does not do

- It is not an intraday system — EOD only, by design.
- It does not implement short-side trading logic.
- It does not have a real point-in-time historical NIFTY-200 membership
  dataset — every historical research run is labeled
  `CURRENT_NIFTY200_HISTORICAL_SIMULATION` (survivorship-biased) unless you
  supply one via the `PointInTimeUniverseProvider` interface.
- It does not know current broker/tax rates — cost figures are placeholders.
- It does not tell you whether the strategy is profitable. It reports
  historical sample statistics; see `docs/RESEARCH_LIMITATIONS.md`.

## Quick start

```bash
pip install -e ".[dev]"
pytest -q                          # 60 tests, all synthetic-fixture based
ruff check src/ tests/
mypy src/ema_scanner --ignore-missing-imports

# Show the fully-resolved, labeled configuration
ema-scanner show-config

# Validate a couple of symbols are reachable (needs real internet access)
ema-scanner validate-data --symbols RELIANCE,TCS

# Automatic EOD scan (resolves the latest completed NSE session itself)
ema-scanner scan

# Manual historical scan (deterministic, validated trading date required)
ema-scanner scan --date 2026-09-21

# Research commands (all need real internet access to fetch data)
ema-scanner event-study --start 2020-01-01 --end 2026-09-21 --symbols RELIANCE,TCS,INFY
ema-scanner backtest --start 2020-01-01 --end 2026-09-21 --exit-rule STOP_ONLY_RESEARCH
ema-scanner walk-forward --start 2015-01-01 --end 2026-09-21 --mode 1
ema-scanner sensitivity --start 2020-01-01 --end 2026-09-21
```

## Date semantics

- **Automatic mode** (`ema-scanner scan`): walks backward from "now" (Asia/
  Kolkata) to the latest NSE session whose close (15:30 IST) has already
  passed. Never analyzes an incomplete session; never uses `today() - 1 day`
  arithmetic (which breaks around weekends/holidays).
- **Manual mode** (`ema-scanner scan --date YYYY-MM-DD`): the date must be an
  actual completed NSE trading session or the run aborts with a clear error —
  it never silently rolls to a nearby date. See `calendar/sessions.py`.

## Documentation index

| File | Contents |
|---|---|
| `docs/NOTEBOOK_AUDIT.md` | Cell-by-cell traceability matrix, bugs found & fixed, what's genuinely new |
| `docs/STRATEGY_SPEC.md` | The frozen strategy specification every production rule traces to |
| `docs/ARCHITECTURE.md` | Module map, the two separate pipelines (live vs. research) |
| `docs/DATA_MODEL.md` | Raw->normalized->research data flow, price modes, cache layout |
| `docs/BACKTEST_METHODOLOGY.md` | Signal generation vs. event study vs. backtest vs. walk-forward vs. sensitivity |
| `docs/RESEARCH_LIMITATIONS.md` | Everything not yet validated — read this |
| `docs/DATA_SOURCES.md` | What was actually verified (and how), what wasn't |
| `CHANGELOG.md` | Version history |

## Project layout

```
configs/default.yaml       Typed, labeled configuration (every parameter
                            tagged SOURCE_DERIVED_RULE / RESEARCH_HYPOTHESIS /
                            OPTIONAL_FILTER / PLACEHOLDER_UNVERIFIED / etc.)
src/ema_scanner/           The package (see ARCHITECTURE.md for the full map)
tests/{unit,lookahead,regression,integration}/
                            60 passing tests, incl. the critical no-lookahead
                            regression suite
notebooks/                 The original notebook, unmodified
docs/                      This documentation set
outputs/                   Scan/research outputs land here (git-ignored)
data/cache/                Parquet data cache (git-ignored)
```

## Troubleshooting

- `ABORT_UNIVERSE_FETCH`: the NIFTY-200 CSV URL in `configs/default.yaml` is
  unreachable or returned an implausibly small list — verify the URL is still
  current at nseindia.com (see `docs/DATA_SOURCES.md`).
- `DATA_UNAVAILABLE`: a data provider failed for a symbol; the run continues
  for other symbols and logs the failure (see `outputs/logs/run.log`) rather
  than substituting synthetic data.
- `AnalysisDateError`: a manually requested `--date` is not an actual NSE
  trading session — pick a real trading date.
