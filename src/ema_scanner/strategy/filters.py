"""Optional filters (brief Section 35, 82).

Every filter here is OFF by default / diagnostic-only unless the config
explicitly enables it. None is silently mandatory. These operate on an
already-built feature frame and either return it unchanged (filter off / not
applicable) or narrow it.
"""
from __future__ import annotations

import pandas as pd

from ema_scanner.config import LiquidityConfig
from ema_scanner.features.liquidity import apply_liquidity_filter


def apply_optional_filters(df: pd.DataFrame, liquidity_cfg: LiquidityConfig) -> pd.DataFrame:
    df = apply_liquidity_filter(
        df,
        enabled=liquidity_cfg.enabled,
        min_price=liquidity_cfg.min_price,
        min_average_daily_traded_value=liquidity_cfg.min_average_daily_traded_value,
        min_average_volume=liquidity_cfg.min_average_volume,
    )
    return df
