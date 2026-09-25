"""Execution model (notebook Cell 34's `resolve_execution_price`; audit row 27;
Phase-2 Section 12 -- BLOCKER fix).

**Bug fixed:** v1 fell back to "the next row in the dataframe" when the
calendar's `next_session` date wasn't present in the data. That's dangerous in
real research: a missing session could mean a suspended security, a bad data
delivery, or a genuine provider gap -- using "whatever the next row happens to
be" silently papers over exactly the kind of data problem that should stop
and be investigated. The calendar-resolved execution date is now REQUIRED to
match an actual bar in the data; if it doesn't, the caller gets a `DATA_GAP`
status and NO execution price, rather than a silently-substituted one.

Signal DETECTION (an EOD close) remains explicitly separate from EXECUTION (a
configurable, modeled fill). `execution_date` is resolved from the exchange
calendar's `next_session`, never `date + timedelta(days=1)`.
"""
from __future__ import annotations

from typing import Literal

import pandas as pd

from ema_scanner.calendar.nse import NSECalendar
from ema_scanner.models import ExecutionRecord

ExecutionStatus = Literal["OK", "DATA_GAP"]


def resolve_execution_price(
    df: pd.DataFrame, signal_date: pd.Timestamp, calendar: NSECalendar,
    execution_model: Literal["same_close", "next_open", "next_close"] = "next_open",
) -> ExecutionRecord:
    idx = df.index
    signal_price = float(df.loc[signal_date, "Close"])

    if execution_model == "same_close":
        return ExecutionRecord(
            signal_date=signal_date, signal_price=signal_price, execution_model=execution_model,
            execution_date=signal_date, execution_price=signal_price, status="OK",
        )

    next_date = calendar.next_session(signal_date)
    if next_date is None or next_date not in idx:
        # NO positional ("next dataframe row") fallback in production code --
        # see module docstring. The caller must treat this as a data gap, not
        # silently advance to an arbitrary row.
        return ExecutionRecord(
            signal_date=signal_date, signal_price=signal_price, execution_model=execution_model,
            execution_date=None, execution_price=None, status="DATA_GAP",
        )

    if execution_model == "next_open":
        price = float(df.loc[next_date, "Open"])
    elif execution_model == "next_close":
        price = float(df.loc[next_date, "Close"])
    else:
        raise ValueError(f"Unknown execution_model: {execution_model!r}")
    return ExecutionRecord(
        signal_date=signal_date, signal_price=signal_price, execution_model=execution_model,
        execution_date=next_date, execution_price=price, status="OK",
    )
