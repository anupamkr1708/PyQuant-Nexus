"""Typed configuration models.

Replaces the notebook's single mutable `Config` class (Cell 6) with structured,
validated, versioned configuration loaded from YAML. No strategy parameter lives
hard-coded inside a function body anywhere in this package (Section 63 of the
refactor brief: "no magic numbers") — if you find one, it is a bug.
"""
from __future__ import annotations

from pathlib import Path
from typing import Literal, cast

import yaml
from pydantic import BaseModel, Field

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parents[2] / "configs" / "default.yaml"


class EMAConfig(BaseModel):
    fast: int = 10
    medium: int = 20
    structural: int = 89
    long: int = 200
    seed_method: Literal["sma", "first_obs"] = "sma"


class SwingConfig(BaseModel):
    left_bars: int = 5
    right_bars: int = 5


class VolatilityConfig(BaseModel):
    atr_period: int = 14


class ClusterConfig(BaseModel):
    width_lookback: int = 252
    compression_percentile: float = 0.20
    expansion_percentile: float = 0.80
    flat_band_percentile: float = 0.10


class DefinitionsConfig(BaseModel):
    sequential_crossover_max_gap_sessions: int = 10
    compression_expansion_lookahead_days: int = 10
    enabled: list[Literal["A", "B", "C", "D"]] = Field(default_factory=lambda: cast("list[Literal['A','B','C','D']]", ["A", "B", "C", "D"]))


class PullbackConfig(BaseModel):
    shallow_atr: float = 1.0
    moderate_atr: float = 2.5
    deep_atr: float = 4.0
    breakout_memory_bars: int = 60


class EntriesConfig(BaseModel):
    enabled: list[Literal["A", "B", "C", "D", "E"]] = Field(
        default_factory=lambda: cast("list[Literal['A','B','C','D','E']]", ["A", "B", "C", "D", "E"])
    )


class RegimeConfig(BaseModel):
    benchmark: Literal["NIFTY50", "NIFTY200", "CUSTOM"] = "NIFTY50"
    index_ema_fast: int = 20
    index_ema_medium: int = 50
    index_ema_structural: int = 89
    index_ema_long: int = 200


class RelativeStrengthConfig(BaseModel):
    windows: list[int] = Field(default_factory=lambda: [20, 60, 120])


class LiquidityConfig(BaseModel):
    enabled: bool = False
    min_price: float = 0.0
    min_average_daily_traded_value: float = 0.0
    min_average_volume: float = 0.0
    min_days_with_valid_volume: int = 0


class StrategyConfig(BaseModel):
    version: str = "ema_cluster_v1"
    ema: EMAConfig = Field(default_factory=EMAConfig)
    swing: SwingConfig = Field(default_factory=SwingConfig)
    volatility: VolatilityConfig = Field(default_factory=VolatilityConfig)
    cluster: ClusterConfig = Field(default_factory=ClusterConfig)
    definitions: DefinitionsConfig = Field(default_factory=DefinitionsConfig)
    pullback: PullbackConfig = Field(default_factory=PullbackConfig)
    entries: EntriesConfig = Field(default_factory=EntriesConfig)
    regime: RegimeConfig = Field(default_factory=RegimeConfig)
    relative_strength: RelativeStrengthConfig = Field(default_factory=RelativeStrengthConfig)
    liquidity: LiquidityConfig = Field(default_factory=LiquidityConfig)


class DataConfig(BaseModel):
    min_history_years: int = 4
    max_stale_sessions: int = 5
    refresh_overlap_sessions: int = 10
    primary_provider: Literal["NSE", "YFINANCE"] = "YFINANCE"
    secondary_provider: Literal["NSE", "YFINANCE"] = "NSE"
    price_mode: Literal["RAW", "SPLIT_ADJUSTED", "TOTAL_RETURN_ADJUSTED"] = "SPLIT_ADJUSTED"


class CalendarConfig(BaseModel):
    exchange: str = "NSE"
    timezone: str = "Asia/Kolkata"
    provider: str = "pandas_market_calendars"
    session_open: str = "09:15"
    session_close: str = "15:30"
    eod_data_cutoff: str = "16:00"


class UniverseConfig(BaseModel):
    index_name: str = "NIFTY200"
    source_csv_url: str = "https://archives.nseindia.com/content/indices/ind_nifty200list.csv"
    min_expected_constituents: int = 150


class ExecutionConfig(BaseModel):
    model: Literal["same_close", "next_open", "next_close"] = "next_open"


class RiskConfig(BaseModel):
    risk_per_trade_pct: float = 0.5
    atr_stop_multiple: float = 2.5


class CostsConfig(BaseModel):
    brokerage_pct: float = 0.03
    stt_pct: float = 0.10
    stt_buy_pct: float | None = None
    stt_sell_pct: float | None = None
    exchange_charges_pct: float = 0.00345
    gst_pct: float = 0.18
    stamp_duty_pct: float = 0.0
    stamp_duty_buy_only: bool = True
    sebi_charges_pct: float = 0.0
    slippage_pct: float = 0.05


class WalkForwardConfig(BaseModel):
    train_years: float = 3.0
    test_years: float = 1.0
    step_years: float = 1.0


class BacktestConfig(BaseModel):
    """Phase-2 Section 14: backtest parameters that were previously function
    defaults/magic numbers, now centralized in config."""

    initial_capital: float = 1_000_000.0
    max_concurrent_positions: int = 20
    max_position_pct_of_equity: float = 100.0  # 100 == no additional per-position cap beyond risk sizing
    fixed_horizon_days: int = 20
    minimum_trade_qty: int = 1
    exit_rule: Literal["STOP_ONLY_RESEARCH", "FIXED_HORIZON"] = "STOP_ONLY_RESEARCH"
    entry_model_col: str = "Any_Entry_Triggered"
    cost_scenario: Literal["zero_cost", "low_cost", "base_cost", "high_cost", "stress_cost"] = "base_cost"


class ResearchConfig(BaseModel):
    horizons_days: list[int] = Field(default_factory=lambda: [1, 3, 5, 10, 20, 40])
    walk_forward: WalkForwardConfig = Field(default_factory=WalkForwardConfig)
    backtest: BacktestConfig = Field(default_factory=BacktestConfig)


class Config(BaseModel):
    """Root configuration object. Immutable by convention (pydantic model); use
    `.model_copy(deep=True)` + field overrides (e.g. in sensitivity analysis) rather
    than mutating the shared instance, to avoid the notebook's shared-mutable-global
    pattern (brief Section 62)."""

    strategy: StrategyConfig = Field(default_factory=StrategyConfig)
    data: DataConfig = Field(default_factory=DataConfig)
    calendar: CalendarConfig = Field(default_factory=CalendarConfig)
    universe: UniverseConfig = Field(default_factory=UniverseConfig)
    execution: ExecutionConfig = Field(default_factory=ExecutionConfig)
    risk: RiskConfig = Field(default_factory=RiskConfig)
    costs: CostsConfig = Field(default_factory=CostsConfig)
    research: ResearchConfig = Field(default_factory=ResearchConfig)
    random_seed: int = 42

    def config_hash(self) -> str:
        """Stable hash of the fully-resolved config, for the run manifest (Section 61)."""
        import hashlib
        import json

        payload = json.dumps(self.model_dump(), sort_keys=True, default=str)
        return hashlib.sha256(payload.encode()).hexdigest()[:16]


def load_config(path: str | Path | None = None) -> Config:
    """Load config from YAML. Falls back to configs/default.yaml. Every field has a
    pydantic default too, so a missing/partial YAML still produces a valid, fully
    labeled Config rather than failing silently on missing keys."""
    p = Path(path) if path else DEFAULT_CONFIG_PATH
    if not p.exists():
        return Config()
    with open(p) as f:
        raw = yaml.safe_load(f) or {}
    return Config(**raw)
