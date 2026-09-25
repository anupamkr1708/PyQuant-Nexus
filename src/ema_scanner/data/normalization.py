"""Provider-agnostic normalization + price-mode selection (brief Sections 21-22).

Keeps raw provider output separate from the "research" price series the
feature engine consumes. The active `price_mode` decides which column becomes
`Close` for EMA/signal/stop calculations — this choice is explicit and
recorded, never left to a provider default (brief Section 21).
"""
from __future__ import annotations

import pandas as pd

REQUIRED_COLS = ["Open", "High", "Low", "Close", "Volume"]


def normalize_provider_frame(raw: pd.DataFrame, price_mode: str = "SPLIT_ADJUSTED") -> pd.DataFrame:
    """
    RAW:               use provider's raw Open/High/Low/Close as-is.
    SPLIT_ADJUSTED:     if an `AdjClose` column exists (yfinance), rescale
                         Open/High/Low/Close by the AdjClose/Close ratio so all
                         four series share a consistent split-adjusted basis
                         (yfinance's AdjClose already reflects splits+dividends
                         when auto_adjust semantics are considered; here we use
                         it purely as a SPLIT adjustment factor, consistent
                         with the config's SPLIT_ADJUSTED label. See
                         DATA_MODEL.md for the exact definition used.).
    TOTAL_RETURN_ADJUSTED: NOT IMPLEMENTED — would require a dividend
                         reinvestment model this refactor does not build
                         (brief Section 99: don't invent it silently). Raises.
    """
    df = raw.copy()
    missing = set(REQUIRED_COLS) - set(df.columns)
    if missing:
        raise ValueError(f"normalize_provider_frame: missing required columns {sorted(missing)}")

    if price_mode == "RAW":
        return df[REQUIRED_COLS]
    if price_mode == "SPLIT_ADJUSTED":
        if "AdjClose" in df.columns:
            ratio = (df["AdjClose"] / df["Close"]).replace([float("inf"), -float("inf")], pd.NA).ffill().bfill().fillna(1.0)
            out = df.copy()
            for col in ["Open", "High", "Low", "Close"]:
                out[col] = out[col] * ratio
            return out[REQUIRED_COLS]
        return df[REQUIRED_COLS]  # no AdjClose available (e.g. NSE bhavcopy) -> raw is already the best we have
    if price_mode == "TOTAL_RETURN_ADJUSTED":
        raise NotImplementedError(
            "TOTAL_RETURN_ADJUSTED price mode is not implemented (would require a dividend "
            "reinvestment model not present in the source notebook or this refactor). "
            "Use RAW or SPLIT_ADJUSTED."
        )
    raise ValueError(f"Unknown price_mode: {price_mode!r}")
