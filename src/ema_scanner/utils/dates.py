"""Small date helpers. No `date + timedelta` next-trading-day arithmetic lives
here (brief Section 41) — use calendar.nse.NSECalendar.next_session instead."""
from __future__ import annotations

import pandas as pd


def to_ts(x) -> pd.Timestamp:
    return pd.Timestamp(x).normalize()
