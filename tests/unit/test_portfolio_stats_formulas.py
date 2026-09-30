"""BLOCKER 18/19 (Phase-3): portfolio statistics formula audit with a
deterministic fixture and hand-computed expected values -- not just renamed
formulas, but numerically verified ones.
"""
import numpy as np
import pandas as pd
import pytest

from ema_scanner.research.statistics import portfolio_stats_from_equity_curve


def test_cagr_uses_exact_elapsed_days_hand_computed():
    """Equity exactly doubles over exactly 365 elapsed calendar days ->
    CAGR must be exactly 100% (not off by a session-count approximation)."""
    dates = pd.bdate_range("2020-01-01", periods=2)
    dates = pd.DatetimeIndex([dates[0], dates[0] + pd.Timedelta(days=365)])
    eq = pd.DataFrame({"cash": [100_000.0, 200_000.0], "positions_value": [0.0, 0.0], "equity": [100_000.0, 200_000.0]}, index=dates)
    stats = portfolio_stats_from_equity_curve(eq)
    expected_years = 365 / 365.25
    expected_cagr = ((2.0) ** (1 / expected_years) - 1.0) * 100.0
    assert stats["cagr_pct"] == pytest.approx(expected_cagr, rel=1e-9)


def test_max_drawdown_hand_computed():
    """Equity path: 100 -> 120 -> 90 -> 110. Peak before the trough is 120;
    trough is 90 -> drawdown = 90/120 - 1 = -25%."""
    dates = pd.bdate_range("2021-01-01", periods=4)
    eq = pd.DataFrame({
        "cash": [100.0, 120.0, 90.0, 110.0], "positions_value": [0.0] * 4,
        "equity": [100.0, 120.0, 90.0, 110.0],
    }, index=dates)
    stats = portfolio_stats_from_equity_curve(eq)
    assert stats["max_drawdown_pct"] == pytest.approx(-25.0, rel=1e-9)


def test_max_drawdown_duration_hand_computed():
    """Underwater (below the running peak) for exactly 3 consecutive
    sessions: 100(peak) -> 90 -> 95 -> 99 -> 101(new peak) -> 100."""
    dates = pd.bdate_range("2021-01-01", periods=6)
    values = [100.0, 90.0, 95.0, 99.0, 101.0, 100.0]
    eq = pd.DataFrame({"cash": values, "positions_value": [0.0] * 6, "equity": values}, index=dates)
    stats = portfolio_stats_from_equity_curve(eq)
    assert stats["max_drawdown_duration_sessions"] == 3


def test_sharpe_zero_risk_free_hand_computed():
    """Constant daily return of exactly 1% every day: mean=0.01, std=0 ->
    Sharpe is undefined (NaN) since std=0. Use two alternating returns
    instead so std is well-defined and hand-computable."""
    dates = pd.bdate_range("2021-01-01", periods=5)
    # Returns: +2%, -1%, +2%, -1% (equity path from 100)
    equity = [100.0]
    for r in [0.02, -0.01, 0.02, -0.01]:
        equity.append(equity[-1] * (1 + r))
    eq = pd.DataFrame({"cash": equity, "positions_value": [0.0] * 5, "equity": equity}, index=dates)
    stats = portfolio_stats_from_equity_curve(eq, risk_free_rate_annual=0.0)

    daily_rets = pd.Series(equity).pct_change().dropna()
    expected_sharpe = (daily_rets.mean() * 252 - 0.0) / (daily_rets.std() * np.sqrt(252))
    assert stats["sharpe"] == pytest.approx(expected_sharpe, rel=1e-9)


def test_sharpe_with_nonzero_risk_free_rate_shifts_result():
    dates = pd.bdate_range("2021-01-01", periods=5)
    equity = [100.0]
    for r in [0.02, -0.01, 0.02, -0.01]:
        equity.append(equity[-1] * (1 + r))
    eq = pd.DataFrame({"cash": equity, "positions_value": [0.0] * 5, "equity": equity}, index=dates)
    stats_zero_rf = portfolio_stats_from_equity_curve(eq, risk_free_rate_annual=0.0)
    stats_with_rf = portfolio_stats_from_equity_curve(eq, risk_free_rate_annual=6.0)
    assert stats_with_rf["sharpe"] < stats_zero_rf["sharpe"]
    assert stats_with_rf["risk_free_rate_annual"] == 6.0


def test_sortino_uses_mar_threshold_not_just_negative_returns():
    """With MAR set to +1% (annualized-equivalent-per-day threshold high
    enough to reclassify a small positive return as 'downside'), Sortino
    must differ from the MAR=0 case."""
    dates = pd.bdate_range("2021-01-01", periods=6)
    equity = [100.0]
    for r in [0.005, 0.02, -0.01, 0.005, 0.03]:  # includes a small +0.5% day
        equity.append(equity[-1] * (1 + r))
    eq = pd.DataFrame({"cash": equity, "positions_value": [0.0] * 6, "equity": equity}, index=dates)

    stats_mar0 = portfolio_stats_from_equity_curve(eq, mar_annual=0.0)
    stats_mar_high = portfolio_stats_from_equity_curve(eq, mar_annual=100.0)  # ~0.4%/day MAR, reclassifies the +0.5% day as downside
    assert stats_mar_high["sortino"] != stats_mar0["sortino"]


def test_notional_turnover_is_distinct_from_trade_frequency():
    """BLOCKER 18: trade_frequency_per_year (count-based) and
    notional_turnover_pct (notional/equity-based) must be reported
    separately and must NOT be numerically conflated."""
    dates = pd.bdate_range("2021-01-01", periods=252)  # ~1 year
    equity = np.full(252, 100_000.0)
    eq = pd.DataFrame({"cash": equity, "positions_value": [0.0] * 252, "equity": equity}, index=dates)

    trade_log = pd.DataFrame({
        "net_pnl": [100.0, -50.0, 200.0],
        "entry_price": [50.0, 100.0, 200.0],
        "quantity": [1000, 500, 250],  # notional: 50000, 50000, 50000 = 150000 total
    })
    stats = portfolio_stats_from_equity_curve(eq, trade_log)
    assert stats["trade_count"] == 3
    expected_years = (dates[-1] - dates[0]).days / 365.25
    assert stats["trade_frequency_per_year"] == pytest.approx(3 / expected_years, rel=1e-6)
    expected_notional_turnover_pct = (150_000.0 / 100_000.0) * 100.0
    assert stats["notional_turnover_pct"] == pytest.approx(expected_notional_turnover_pct, rel=1e-9)
    assert stats["notional_turnover_pct"] != stats["trade_frequency_per_year"]
    assert "turnover_trades_per_year" not in stats  # the old, ambiguous name must be gone
