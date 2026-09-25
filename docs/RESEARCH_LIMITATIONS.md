# Research Limitations

**Phase-2 status (see docs/PHASE2_AUDIT.md for the full itemized response to
the adversarial review):** the correctness/architecture blockers identified
in the Phase-2 review have been fixed and tested (price semantics, cache-first
data flow, provider factory wiring, manual-date safety, analysis-date data
gate, warm-up engine, cross-sectional RS percentile, backtest execution
timeline, positional-fallback removal, stop/entry geometry, event-vs-portfolio
statistics separation, scanner output semantics, manifest correctness). What
follows is still accurate: no real market data has been used to validate any
of this, for the same environment reason as before (no network access to
yfinance/NSE in this build environment).

Per brief Section 109 ("do not hide limitations") and Section 102 ("do not
declare a strategy profitable"). Read this before trusting any output of this
system for real capital decisions.

## 1. No live-data validation was performed in this build environment

The sandboxed tool environment this refactor was built in restricts outbound
network access to software package registries (`pypi.org`, `npmjs.org`,
`github.com`, etc.) and cannot reach `finance.yahoo.com` or `nseindia.com`.
Consequently:

- `data/yfinance.py` has been tested only against a **mocked** `yf.download`
  (see `tests/unit/test_yfinance_provider.py`) — the exclusive-`end` fix and
  error handling are verified logically, but the code has never actually
  pulled a live NSE quote in this environment.
- `data/nse.py` is an **interface only** — its endpoint is deliberately left
  unconfigured rather than guessed (see `DATA_SOURCES.md`).
- No real historical backtest, event study, or walk-forward run has been
  executed against actual NIFTY 200 data. Every number in this repository's
  test suite comes from synthetic fixtures (`tests/fixtures/synthetic.py`),
  used strictly for pipeline-plumbing verification, never presented as
  research results.
- The universe fetch (`universe/current.py`), the NIFTY-200 CSV URL, and the
  benchmark (`^NSEI`) download have not been confirmed reachable from a normal
  network in this session.

**Action required before trusting this for real signals or research:** run
`ema-scanner validate-data` and a real `ema-scanner scan` from a machine with
ordinary internet access, and review the resulting `run_manifest.json` and
data-quality summary before acting on any signal.

## 2. Point-in-time universe history does not exist

There is no historical NIFTY-200-constituent-membership data source wired up
(same gap as the source notebook — see `NOTEBOOK_AUDIT.md` §2). Every
historical research run is necessarily `CURRENT_NIFTY200_HISTORICAL_SIMULATION`
— survivorship-biased by construction, and labeled as such everywhere. This is
a real, unresolved limitation, not a cosmetic one: a proper backtest would
need a licensed or self-maintained index-membership history.

## 3. Transaction costs are unverified placeholders

`configs/default.yaml: costs` values were copied unchanged from the source
notebook and were not checked against a current broker fee schedule or
current STT/GST/SEBI/stamp-duty rates (brief Section 45 explicitly required
this verification, which could not be completed — no access to an
authoritative fee-schedule source in this environment). Any net-of-cost
number this system produces should be treated as illustrative until you
substitute your own confirmed rates.

## 4. The NSE calendar library is a helper, not ground truth

`pandas_market_calendars`'s `XNSE` calendar was spot-checked against known
2026 holidays and appears correct for ordinary sessions, but its handling of
irregular special sessions (Muhurat Trading in particular) was not verified
and a quick check suggested it may not model a distinct Saturday/Sunday
Muhurat session at all. `calendar/nse.py`'s `special_session_overrides` exists
for exactly this reason but ships empty — you must populate it yourself from
an official NSE circular for any year you're analyzing across Diwali.

## 5. The portfolio backtest engine is new, unvalidated code

`research/backtest.py` does not exist in the source notebook at all (the
notebook only implements an event study). It has been exercised only against
synthetic data to confirm accounting invariants (cash never negative, equity
reconciles, every trade has an exit). It has NOT been reviewed by a second
engineer, has NOT been run against real data, and its documented
simplifications (long-only, one position per symbol, first-come-by-dict-order
entry priority on a given day, approximate cash-timing) should all be treated
as open questions before relying on its output.

## 6. True walk-forward (Mode 2) is deliberately simple

`research/walk_forward.py::true_walk_forward` selects parameters via a grid
search maximizing training-window median return — a genuinely nested
train/test split, but not a sophisticated or rigorously validated selection
procedure. Small sample sizes per fold and the multiple-comparisons problem
(brief Section 54) are real risks that have not been separately corrected for.

## 7. Statistical inference is a first pass

`research/statistics.py::block_bootstrap_ci` clusters by ticker, which
addresses one form of dependence (overlapping signals within the same stock)
but not others (e.g., market-wide days where many stocks signal
simultaneously — cross-sectional dependence). Treat confidence intervals as
indicative, not as a rigorously reviewed inferential procedure.

## 8. Short-side logic is not implemented

Only long-side entries/stops/backtest logic exists, consistent with the
source notebook. The source note's reference to "reverse logic... conceptually
for shorts" is not built out anywhere in this codebase.

## 9. Corporate actions are only partially handled

`data/corporate_actions.py` is an interface stub. Price adjustment relies
entirely on whatever `yfinance`'s `AdjClose` column already encodes for
splits/dividends; there is no independent corporate-action dataset, no
explicit merger/symbol-change handling beyond the minimal
`universe/security_master.py` scaffold, and total-return adjustment is not
implemented at all (`data/normalization.py` raises `NotImplementedError`
rather than approximating it).

## 10. Lint / type-check status

`ruff check` passes with 6 remaining findings, all intentional broad
`except Exception` blocks inside grid-search loops (`research/sensitivity.py`,
`research/walk_forward.py`) where one bad parameter combination or one bad
ticker must not crash an entire multi-hour research run — documented at each
site with a `# noqa` and rationale. `mypy` reports a small number of
Literal-vs-`str` friction points at the CLI boundary (Click options arrive as
plain `str`) and one third-party stub gap (`pandas_market_calendars` has no
type stubs) — none of these reflect a runtime defect; see the CLI's option
`type=click.Choice([...])` for actual runtime validation.

## Bottom line

Nothing in this repository should be read as "this strategy is profitable" or
as investment advice. It is a research and EOD decision-support scaffold whose
correctness properties (no look-ahead, calendar-correct dates, explicit cost/
execution assumptions, disclosed survivorship bias) have been engineered and
tested; its **economic conclusions have not been produced at all**, because no
real-data run has been executed yet.
