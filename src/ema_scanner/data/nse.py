"""NSE PRIMARY provider (brief Sections 13, 14, 100).

**VERIFICATION STATUS (read before enabling in production):** This module's bash
tool network in the environment this refactor was built in is restricted to
package registries (pypi.org, npmjs.org, github.com, etc.) and cannot reach
nseindia.com, so the exact current PUBLIC retail bhavcopy CSV endpoint/schema
could not be fetched and inspected directly as part of this refactor. A web
search on 2026-09-23 surfaced several *member-facing* NSE circulars (e.g.
NSE/MSD/74764, /75001, /75910 — "Streamlining EOD information dissemination
related to Bhavcopy") describing an active migration of Extranet/FTP bhavcopy
delivery for trading MEMBERS, with further changes effective October 12, 2026.
Those circulars are about a different consumption channel (member Extranet)
than the public `archives.nseindia.com` website this module targets, but they
are strong evidence that NSE's bhavcopy delivery mechanisms are genuinely in
flux right now — exactly the caution the refactor brief (Section 14) asks for.
See DATA_SOURCES.md for the full citation trail.

Per brief Section 100 ("Do not invent URLs or endpoints"), this module does
**not** guess a specific bhavcopy filename pattern. `endpoint_template` below is
left as an explicit, clearly-labeled placeholder that raises `NotImplementedError`
with instructions rather than silently fetching something that might be wrong.
Wire up the verified current endpoint here once you've confirmed it from
https://www.nseindia.com/all-reports (the UDiFF-based "Common Bhavcopy Final
(zip)" or CSV equity report). Until then, `configs/default.yaml` defaults
`primary_provider: YFINANCE` (the verified, implemented provider) rather than
defaulting production behavior to an unverified endpoint.

The CSV column-parsing logic below reflects the UDiFF Common Bhavcopy schema
as publicly documented (TradDt, TckrSymb, SctySrs, OpnPric, HghPric, LwPric,
ClsPric, TtlTradgVol, ...); it is defensive — if the fetched file's columns
don't match what's expected, it raises `DataUnavailableError` describing the
mismatch rather than silently mis-mapping columns.
"""
from __future__ import annotations

import io

import pandas as pd

from ema_scanner.data.base import DataProvider, DataUnavailableError, ProviderMetadata

EXPECTED_UDIFF_COLUMNS = {
    "TradDt", "TckrSymb", "SctySrs", "OpnPric", "HghPric", "LwPric", "ClsPric", "TtlTradgVol",
}


class NSEBhavcopyProvider(DataProvider):
    name = "nse_bhavcopy"

    # UNVERIFIED — see module docstring. Do not enable in production without
    # confirming this against the current public NSE bhavcopy page.
    endpoint_template: str | None = None

    def get_daily_ohlcv(self, symbol: str, start_date: str, end_date: str) -> tuple[pd.DataFrame, ProviderMetadata]:
        if self.endpoint_template is None:
            raise DataUnavailableError(
                "NSEBhavcopyProvider.endpoint_template is not configured. The exact current "
                "public NSE UDiFF bhavcopy CSV URL could not be verified in this environment "
                "(see docs/DATA_SOURCES.md). Confirm the endpoint from "
                "https://www.nseindia.com/all-reports and set endpoint_template before use, "
                "or use YFinanceProvider (already implemented and configured as the default "
                "primary provider) in the meantime."
            )
        raise NotImplementedError(
            "NSE bhavcopy fetch/parse would run here once endpoint_template is verified. "
            "See _parse_bhavcopy_csv for the (defensive, schema-checked) parsing logic."
        )

    @staticmethod
    def _parse_bhavcopy_csv(raw_csv_bytes: bytes, symbol: str) -> pd.DataFrame:
        """Defensive parser for a single day's UDiFF CM bhavcopy CSV, filtered to
        one equity symbol's EQ series row. Raises DataUnavailableError (not a
        silent mis-parse) if the expected columns aren't present."""
        df = pd.read_csv(io.BytesIO(raw_csv_bytes))
        missing = EXPECTED_UDIFF_COLUMNS - set(df.columns)
        if missing:
            raise DataUnavailableError(
                f"NSE bhavcopy CSV is missing expected columns {sorted(missing)} — "
                f"the schema may have changed; refusing to guess a mapping."
            )
        row_mask = (df["TckrSymb"] == symbol) & (df["SctySrs"] == "EQ")
        rows = df[row_mask]
        if rows.empty:
            raise DataUnavailableError(f"No EQ-series bhavcopy row found for {symbol}")
        out = pd.DataFrame({
            "Open": rows["OpnPric"].astype(float), "High": rows["HghPric"].astype(float),
            "Low": rows["LwPric"].astype(float), "Close": rows["ClsPric"].astype(float),
            "Volume": rows["TtlTradgVol"].astype(float),
        })
        out.index = pd.to_datetime(rows["TradDt"])
        out.index.name = "Date"
        return out.sort_index()
