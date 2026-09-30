"""Brief Section 15: yfinance `end` is exclusive; requested final date must be
included. Uses monkeypatching so this test never touches the live network."""
import pandas as pd
import pytest

from ema_scanner.data.yfinance import YFinanceProvider


def test_end_date_is_inclusive(monkeypatch):
    captured = {}

    def fake_download(**kwargs):
        captured.update(kwargs)
        dates = pd.date_range("2026-09-01", "2026-09-21", freq="B")
        return pd.DataFrame(
            {"Open": 100.0, "High": 101.0, "Low": 99.0, "Close": 100.5, "Adj Close": 100.5, "Volume": 1000},
            index=dates,
        )

    import yfinance as yf
    monkeypatch.setattr(yf, "download", fake_download)

    provider = YFinanceProvider()
    df, _meta = provider.get_daily_ohlcv("RELIANCE", "2026-09-01", "2026-09-21")

    # The provider must have requested an EXCLUSIVE end one day past the caller's
    # inclusive end_date, so that 2026-09-21 is actually returned.
    assert captured["end"] == "2026-09-22"
    assert pd.Timestamp("2026-09-21") in df.index


def test_raises_data_unavailable_on_empty_result(monkeypatch):
    import yfinance as yf
    monkeypatch.setattr(yf, "download", lambda **kw: pd.DataFrame())

    from ema_scanner.data.base import DataUnavailableError
    provider = YFinanceProvider()
    with pytest.raises(DataUnavailableError):
        provider.get_daily_ohlcv("BOGUS", "2026-01-01", "2026-01-31")


def test_repair_is_disabled_and_recorded_in_metadata(monkeypatch):
    """BLOCKER 24 (Phase-3): repair=False by default, and the choice must be
    auditable via ProviderMetadata rather than a hidden preprocessing step."""
    captured = {}

    def fake_download(**kwargs):
        captured.update(kwargs)
        dates = pd.date_range("2026-09-01", "2026-09-05", freq="B")
        return pd.DataFrame(
            {"Open": 100.0, "High": 101.0, "Low": 99.0, "Close": 100.5, "Adj Close": 100.5, "Volume": 1000},
            index=dates,
        )

    import yfinance as yf
    monkeypatch.setattr(yf, "download", fake_download)

    provider = YFinanceProvider()
    _df, meta = provider.get_daily_ohlcv("RELIANCE", "2026-09-01", "2026-09-05")

    assert captured["repair"] is False
    assert meta.vendor_repair_enabled is False
