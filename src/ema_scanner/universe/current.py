"""Live NIFTY 200 universe (notebook Cell 8; audit row 12).

SOURCE-DERIVED RULE, preserved exactly: fetched live from NSE at runtime,
NEVER hard-coded, and fails loudly (ABORT_UNIVERSE_FETCH, brief Section 98) if
the CSV can't be fetched or the row count looks implausible.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd
import requests

from ema_scanner.universe.models import UniverseConstituent


class UniverseFetchError(RuntimeError):
    pass


def fetch_current_nifty200(csv_url: str, min_expected_constituents: int = 150, timeout: int = 30) -> tuple[list[UniverseConstituent], dict]:
    headers = {"User-Agent": "Mozilla/5.0 (ema-scanner research tool)"}
    try:
        resp = requests.get(csv_url, headers=headers, timeout=timeout)
        resp.raise_for_status()
    except Exception as e:
        raise UniverseFetchError(f"ABORT_UNIVERSE_FETCH: could not fetch {csv_url}: {e}") from e

    try:
        from io import StringIO
        df = pd.read_csv(StringIO(resp.text))
    except Exception as e:
        raise UniverseFetchError(f"ABORT_UNIVERSE_FETCH: could not parse CSV from {csv_url}: {e}") from e

    symbol_col = next((c for c in df.columns if c.strip().lower() == "symbol"), None)
    name_col = next((c for c in df.columns if "company" in c.strip().lower()), None)
    industry_col = next((c for c in df.columns if "industry" in c.strip().lower() or "sector" in c.strip().lower()), None)
    if symbol_col is None:
        raise UniverseFetchError(f"ABORT_UNIVERSE_FETCH: no Symbol column found in {csv_url}; columns={list(df.columns)}")

    if len(df) < min_expected_constituents:
        raise UniverseFetchError(
            f"ABORT_UNIVERSE_FETCH: only {len(df)} rows returned from {csv_url}, "
            f"expected at least {min_expected_constituents} — refusing to proceed with a "
            f"suspiciously small universe."
        )

    constituents = [
        UniverseConstituent(
            symbol=str(row[symbol_col]).strip(), company_name=str(row[name_col]).strip() if name_col else None,
            sector=str(row[industry_col]).strip() if industry_col else None,
            provider_ticker=str(row[symbol_col]).strip(), effective_date=None,
        )
        for _, row in df.iterrows()
    ]
    metadata = {
        "universe_source": csv_url, "universe_retrieval_date": datetime.now(timezone.utc).isoformat(),
        "row_count": len(constituents),
    }
    return constituents, metadata
