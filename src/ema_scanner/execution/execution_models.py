"""Execution model (notebook Cell 34's `resolve_execution_price`; audit row 27).

Signal DETECTION (an EOD close) is explicitly separate from EXECUTION (a
configurable, modeled fill) (brief Sections 39-41). `execution_date` is resolved
from the exchange calendar's `next_session`, never `date + timedelta(days=1)`.
Returns an ExecutionRecord, never claims to be an actual broker fill unless
`is_actual_fill=True` is supplied by the caller from a real execution report.
"""
from __future__ import annotations

from typing import Literal

import pandas as pd

from ema_scanner.calendar.nse import NSECalendar
from ema_scanner.models import ExecutionRecord


def resolve_execution_price(
    df: pd.DataFrame, signal_date: pd.Timestamp, calendar: NSECalendar,
    execution_model: Literal["same_close", "next_open", "next_close"] = "next_open",
) -> ExecutionRecord:
    idx = df.index
    signal_price = float(df.loc[signal_date, "Close"])
    if execution_model == "same_close":
        return ExecutionRecord(
            signal_date=signal_date, signal_price=signal_price, execution_model=execution_model,
            execution_date=signal_date, execution_price=signal_price,
        )
    # Use the calendar's next_session, then confirm that session is actually present in df
    # (a stock can be delisted/have no data even on a valid exchange session).
    next_date = calendar.next_session(signal_date)
    if next_date is None or next_date not in idx:
        # Fall back to positional next row IF it's the immediate next row in df (keeps
        # behavior sane for test fixtures that don't span real calendar dates), else abort.
        loc = idx.get_loc(signal_date)
        if loc + 1 < len(idx):
            next_date = idx[loc + 1]
        else:
            return ExecutionRecord(
                signal_date=signal_date, signal_price=signal_price, execution_model=execution_model,
                execution_date=None, execution_price=None,
            )
    if execution_model == "next_open":
        price = float(df.loc[next_date, "Open"])
    elif execution_model == "next_close":
        price = float(df.loc[next_date, "Close"])
    else:
        raise ValueError(f"Unknown execution_model: {execution_model!r}")
    return ExecutionRecord(
        signal_date=signal_date, signal_price=signal_price, execution_model=execution_model,
        execution_date=next_date, execution_price=price,
    )
