"""Provider factory tests (Phase-2 Section 3 -- BLOCKER: config must actually
control which provider graph is instantiated)."""
from ema_scanner.config import DataConfig
from ema_scanner.data.base import CompositeDataProvider
from ema_scanner.data.factory import build_data_provider
from ema_scanner.data.nse import NSEBhavcopyProvider
from ema_scanner.data.yfinance import YFinanceProvider


def test_default_config_produces_yfinance_primary_nse_secondary():
    cfg = DataConfig()
    provider = build_data_provider(cfg)
    assert isinstance(provider, CompositeDataProvider)
    assert isinstance(provider.providers[0], YFinanceProvider)
    assert isinstance(provider.providers[1], NSEBhavcopyProvider)


def test_changing_primary_provider_changes_the_instantiated_graph():
    cfg = DataConfig(primary_provider="NSE", secondary_provider="YFINANCE")
    provider = build_data_provider(cfg)
    assert isinstance(provider.providers[0], NSEBhavcopyProvider)
    assert isinstance(provider.providers[1], YFinanceProvider)


def test_same_provider_for_both_slots_is_not_duplicated():
    cfg = DataConfig(primary_provider="YFINANCE", secondary_provider="YFINANCE")
    provider = build_data_provider(cfg)
    assert len(provider.providers) == 1
    assert isinstance(provider.providers[0], YFinanceProvider)
