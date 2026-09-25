"""EMA crossover engine (notebook Cell 18; audit row 18).

MATHEMATICAL DEFINITION, preserved exactly:

    bullish crossover: A[t-1] <= B[t-1] and A[t] > B[t]
    bearish crossover: A[t-1] >= B[t-1] and A[t] < B[t]

Alignment != crossover: alignment is a STATE at time t; a crossover is an EVENT
between t-1 and t. Does not assume all six pairwise crossovers occur on the same
day (Section 5 of the brief).
"""
from __future__ import annotations

import pandas as pd

PAIRS: list[tuple[str, str]] = [
    ("EMA10", "EMA20"),
    ("EMA20", "EMA89"),
    ("EMA89", "EMA200"),
    ("EMA10", "EMA89"),
    ("EMA10", "EMA200"),
    ("EMA20", "EMA200"),
]


def bullish_crossover(a: pd.Series, b: pd.Series) -> pd.Series:
    a_prev, b_prev = a.shift(1), b.shift(1)
    return ((a_prev <= b_prev) & (a > b)).fillna(False)


def bearish_crossover(a: pd.Series, b: pd.Series) -> pd.Series:
    a_prev, b_prev = a.shift(1), b.shift(1)
    return ((a_prev >= b_prev) & (a < b)).fillna(False)


def compute_all_crossovers(df: pd.DataFrame, suffix: str = "") -> pd.DataFrame:
    out = df.copy()
    for a_name, b_name in PAIRS:
        a, b = out[f"{a_name}{suffix}"], out[f"{b_name}{suffix}"]
        out[f"BULL_X_{a_name}_{b_name}{suffix}"] = bullish_crossover(a, b)
        out[f"BEAR_X_{a_name}_{b_name}{suffix}"] = bearish_crossover(a, b)
    return out
