"""Warm-up policy (Phase-2 Section 9 -- BLOCKER).

**Bug fixed:** research/CLI commands built features starting exactly at the
user's requested `--start` date, with no prior history fetched. EMA200 (and
especially WEEKLY EMA200, which needs ~200 WEEKS of history, not 200 days),
rolling cluster percentiles (default 252-session lookback), and RS120 all
produce artificially-initialized values for a long stretch after their own
`seed_index`/`min_periods` if given no data before the requested start --
these transient values would previously have leaked into the "evaluation
period" as if they were normal, undistorted signals.

This is an ENGINEERING_DECISION heuristic, not a rigorously derived bound:
EMA is an exponentially-decaying weighted average, so it never becomes
*exactly* independent of its seed, but the seed's influence decays below
floating-point-noticeable levels after roughly 3-5x the period in bars for a
daily EMA. This module is deliberately conservative (see the multipliers
below) rather than exact.
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from ema_scanner.config import Config


@dataclass(frozen=True)
class WarmupPolicy:
    required_daily_sessions: int
    breakdown: dict[str, int]

    def warmup_start(self, requested_start: pd.Timestamp, calendar=None) -> pd.Timestamp:
        """Calendar-days approximation (used to build a provider fetch window);
        callers that also have an `NSECalendar` should prefer stepping back
        `required_daily_sessions` real trading sessions instead (see
        `warmup_start_via_calendar`), which is exact rather than approximate."""
        # ~1.45 calendar days per trading session accounts for weekends; add a
        # small extra buffer for holidays.
        calendar_days = int(self.required_daily_sessions * 1.45) + 15
        return requested_start - pd.Timedelta(days=calendar_days)

    def warmup_start_via_calendar(self, requested_start: pd.Timestamp, calendar) -> pd.Timestamp:
        window_start = requested_start - pd.Timedelta(days=int(self.required_daily_sessions * 1.6) + 30)
        sessions = calendar.valid_sessions(window_start, requested_start)
        if len(sessions) <= self.required_daily_sessions:
            return window_start  # not enough real history exists that far back anyway
        return sessions[-(self.required_daily_sessions + 1)]


def calculate_required_warmup(cfg: Config) -> WarmupPolicy:
    """Centralizes the warm-up calculation so every research/CLI command uses
    the SAME policy (brief: 'centralized WarmupPolicy')."""
    s = cfg.strategy
    breakdown = {
        "daily_ema_long_x3": s.ema.long * 3,
        "weekly_ema_long_in_daily_sessions": s.ema.long * 5 * 3,  # ~200 weeks * 5 sessions/wk, x3 stabilization
        "cluster_width_lookback_plus_buffer": s.cluster.width_lookback + 60,
        "swing_confirmation": (s.swing.left_bars + s.swing.right_bars) * 4,
        "atr_period_x5": s.volatility.atr_period * 5,
        "relative_strength_max_window_x2": max(s.relative_strength.windows) * 2,
        "pullback_breakout_memory": s.pullback.breakout_memory_bars,
    }
    required = max(breakdown.values()) + 50  # flat safety buffer
    return WarmupPolicy(required_daily_sessions=required, breakdown=breakdown)
