"""Typed records used across the pipeline (Section 5, 36, 61 of the refactor brief).

These are the structured objects that replace ad-hoc dict rows in the notebook.
Dataclasses (not pydantic) are used here deliberately: these are created in tight
per-row loops over up to ~200 stocks x thousands of days, so we avoid pydantic's
validation overhead at that volume.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

Direction = Literal["LONG", "SHORT"]
AlignmentState = Literal["BULLISH_ALIGNED", "BEARISH_ALIGNED", "MIXED"]


@dataclass(frozen=True)
class CrossoverEvent:
    """One pairwise EMA crossover event (Section 5 of the brief)."""

    symbol: str
    date: Any  # pd.Timestamp
    timeframe: Literal["DAILY", "WEEKLY"]
    pair: tuple[str, str]
    direction: Literal["BULLISH", "BEARISH"]
    previous_fast: float
    previous_slow: float
    current_fast: float
    current_slow: float
    distance: float
    alignment_before: AlignmentState | None
    alignment_after: AlignmentState | None


@dataclass(frozen=True)
class SwingPoint:
    """A confirmed (or pending) swing pivot (Section 31 of the brief)."""

    symbol: str
    swing_date: Any
    confirmation_date: Any
    kind: Literal["LOW", "HIGH"]
    price: float


@dataclass(frozen=True)
class ExecutionRecord:
    """Separates signal detection from a modeled execution fill (Section 39/40)."""

    signal_date: Any
    signal_price: float
    execution_model: Literal["same_close", "next_open", "next_close"]
    execution_date: Any | None
    execution_price: float | None
    is_actual_fill: bool = False  # True only if a real broker execution is supplied
    label: str = "NEXT_SESSION_EXECUTION_REFERENCE"
    status: Literal["OK", "DATA_GAP"] = "OK"


@dataclass
class CandidateSignal:
    """One row of the EOD scanner output (Section 36/38 of the brief)."""

    symbol: str
    signal_date: Any
    strategy_id: str  # e.g. "EntryD_SwingHighBreakout"
    direction: Direction
    daily_state: AlignmentState | None
    weekly_state: AlignmentState | None
    mtf_state: str | None
    cluster_state: str | None
    entry_trigger: bool
    entry_reason: str
    entry_price_reference: float | None
    stop_reference: float | None
    stop_distance_pct: float | None
    atr: float | None
    relative_strength_60d: float | None
    market_regime: str | None
    data_quality_status: Literal["PASS", "WARN", "FAIL"]
    research_metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class Trade:
    """One closed trade from the portfolio backtest engine (Section 49)."""

    symbol: str
    strategy_id: str
    signal_date: Any
    execution_date: Any
    entry_price: float
    quantity: int
    initial_stop: float
    exit_date: Any | None = None
    exit_price: float | None = None
    exit_reason: str | None = None
    gross_pnl: float | None = None
    costs: float | None = None
    net_pnl: float | None = None
    return_pct: float | None = None
    mae_pct: float | None = None
    mfe_pct: float | None = None
    holding_period_sessions: int | None = None
    stop_source_swing_date: Any | None = None    # Phase-2 Section 20: swing audit trail
    stop_available_date: Any | None = None         # the swing's CONFIRMATION date


@dataclass(frozen=True)
class SymbolFailure:
    """Structured per-symbol failure record (Phase-2 Sections 6, 18) --
    replaces silently `continue`-ing past a missing/failed symbol."""

    symbol: str
    stage: Literal["data_fetch", "quality_gate", "analysis_date_gate", "pipeline", "universe"]
    reason: str


@dataclass
class RunManifest:
    """Per-run provenance record (brief Section 61; Phase-2 Section 22 --
    field names now match the exact required schema, not approximations of
    it: `rows_downloaded` is genuinely a row count, not a symbol count;
    `missing_sessions` is computed, not hard-coded 0; `symbols_*` are
    distinctly named from `universe_count`)."""

    run_id: str
    run_timestamp_utc: str
    analysis_date: str | None
    decision_timestamp: str
    analysis_timezone: str
    calendar_source: str
    calendar_version: str
    universe_source: str
    universe_date: str | None
    universe_mode: str
    universe_count: int
    provider: str
    provider_version: str | None
    python_version: str
    package_versions: dict[str, str]
    config_hash: str
    strategy_version: str
    git_commit: str | None
    git_dirty: bool | None
    symbols_requested: int
    symbols_processed: int
    symbols_failed: int
    rows_downloaded: int
    rows_validated: int
    missing_sessions: int
    stale_symbols: list[str]
    data_quality_counts: dict[str, int]
    runtime_seconds: float
    # Deprecated aliases kept only so any external code reading old manifest
    # field names doesn't hard-crash; DO NOT populate these going forward.
    code_version: str | None = None
    tickers_requested: int | None = None
    tickers_processed: int | None = None
    tickers_failed: int | None = None
    data_provider: str | None = None          # old name for `provider`
    data_quality_summary: dict[str, int] | None = None  # old name for `data_quality_counts`
