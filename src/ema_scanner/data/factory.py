"""Provider factory (Phase-2 Section 3 -- BLOCKER).

**Bug fixed:** v1's CLI commands instantiated `YFinanceProvider()` directly,
so `configs/default.yaml: data.primary_provider/secondary_provider` looked
configurable but had no actual effect on what the running code did. Every
CLI command must now go through `build_data_provider(cfg)` instead of
constructing a provider itself.
"""
from __future__ import annotations

from ema_scanner.config import DataConfig
from ema_scanner.data.base import CompositeDataProvider, DataProvider
from ema_scanner.data.nse import NSEBhavcopyProvider
from ema_scanner.data.yfinance import YFinanceProvider

_PROVIDER_BUILDERS = {
    "NSE": lambda: NSEBhavcopyProvider(),
    "YFINANCE": lambda: YFinanceProvider(),
}


def build_single_provider(name: str) -> DataProvider:
    """Exposed for tooling (e.g. `ema-scanner cross-check-data`) that needs a
    specific named provider rather than the composite fallback chain."""
    return _PROVIDER_BUILDERS[name]()


def build_data_provider(cfg: DataConfig) -> DataProvider:
    """Builds a `CompositeDataProvider` in `[primary, secondary]` order from
    config, deduplicating if the same provider is configured for both slots.
    This is the ONLY place a provider should be constructed from
    configuration -- CLI commands call this, never `YFinanceProvider()` or
    `NSEBhavcopyProvider()` directly."""
    order = [cfg.primary_provider]
    if cfg.secondary_provider != cfg.primary_provider:
        order.append(cfg.secondary_provider)
    providers = [_PROVIDER_BUILDERS[name]() for name in order]
    return CompositeDataProvider(providers)
