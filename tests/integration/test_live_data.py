"""Real-data integration tests (Phase-2 Section 27).

Gated behind `EMA_SCANNER_LIVE=1` -- NEVER runs as part of mandatory CI/test
suite (brief Section 32/33: never present synthetic-data results as real
research, and never make live network calls mandatory for the test suite to
pass). This is the ONLY place in the test suite that is allowed to touch a
real network. It was NOT run in the environment this refactor was built in
(no network access to yfinance/NSE there -- see RESEARCH_LIMITATIONS.md);
run it yourself with `EMA_SCANNER_LIVE=1 pytest tests/integration/test_live_data.py`
from an environment with normal internet access before trusting the data layer.
"""
import os

import pytest

LIVE = os.environ.get("EMA_SCANNER_LIVE") == "1"
pytestmark = pytest.mark.skipif(not LIVE, reason="set EMA_SCANNER_LIVE=1 to run real-network tests")

SMALL_TEST_UNIVERSE = ["RELIANCE", "TCS", "INFY"]
BENCHMARK = "^NSEI"


def test_yfinance_provider_connectivity():
    from ema_scanner.data.yfinance import YFinanceProvider

    provider = YFinanceProvider()
    df, meta = provider.get_daily_ohlcv("RELIANCE", "2026-01-01", "2026-01-31")
    assert not df.empty
    assert meta.source == "yfinance"


def test_calendar_resolves_a_real_completed_session():
    from ema_scanner.calendar.nse import NSECalendar
    from ema_scanner.calendar.sessions import resolve_analysis_date

    cal = NSECalendar()
    resolution = resolve_analysis_date(cal)
    assert resolution.is_trading_day
    assert resolution.exchange_session_complete


def test_end_to_end_feature_generation_on_real_small_universe():
    from ema_scanner.calendar.nse import NSECalendar
    from ema_scanner.calendar.sessions import resolve_analysis_date
    from ema_scanner.config import load_config
    from ema_scanner.data.cache import DataCache
    from ema_scanner.data.factory import build_data_provider
    from ema_scanner.data.quality import validate_ohlc
    from ema_scanner.data.repository import DataRepository
    from ema_scanner.features.regime import compute_market_regime
    from ema_scanner.research.warmup import calculate_required_warmup
    from ema_scanner.strategy.signal_engine import build_stock_feature_frame

    cfg = load_config()
    cal = NSECalendar()
    resolution = resolve_analysis_date(cal)
    provider = build_data_provider(cfg.data)
    repo = DataRepository(provider, DataCache("data/cache"), price_mode=cfg.data.price_mode)
    warmup = calculate_required_warmup(cfg)
    fetch_start = warmup.warmup_start_via_calendar(resolution.resolved_signal_date - __import__("pandas").DateOffset(years=2), cal)

    index_df, _ = repo.get_daily_ohlcv(BENCHMARK, str(fetch_start.date()), str(resolution.resolved_signal_date.date()))
    regime_df = compute_market_regime(index_df)

    for sym in SMALL_TEST_UNIVERSE:
        df, _diag = repo.get_daily_ohlcv(sym, str(fetch_start.date()), str(resolution.resolved_signal_date.date()))
        report = validate_ohlc(df, cal, as_of_date=resolution.resolved_signal_date, max_stale_sessions=cfg.data.max_stale_sessions)
        assert report.status != "FAIL", f"{sym}: {report.issues}"
        feats = build_stock_feature_frame(df, index_df["Close"], regime_df, cfg)
        assert resolution.resolved_signal_date in feats.index
        assert resolution.resolved_signal_date in feats.index
        for col in ("EMA10", "EMA20", "EMA89", "EMA200", "ATR14", "Weekly_State", "Signal_State"):
            assert col in feats.columns, f"missing expected column {col} for {sym}"
