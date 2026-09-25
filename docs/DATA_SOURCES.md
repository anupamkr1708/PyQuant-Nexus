# Data Sources — Verification Log

Per brief Section 100: "verify current official documentation rather than
relying on stale knowledge... Record verified sources and dates... Do not
invent URLs or endpoints." This log records exactly what was checked, how, and
when, and — just as important — what could **not** be checked in this build
environment.

**Environment constraint that shaped this log:** the sandboxed tool
environment this refactor was built in restricts outbound network access (via
`bash_tool`) to software package registries (`pypi.org`, `npmjs.org`,
`github.com`, `archive.ubuntu.com`, etc.) — it cannot reach `nseindia.com`,
`finance.yahoo.com`, or any market-data host directly. Web search was
available and used where noted; direct HTTP fetches of data endpoints were
not possible. This is disclosed prominently in `RESEARCH_LIMITATIONS.md` as
well.

## Verified via package registry (pip), 2026-09-23

| Claim | Method | Result |
|---|---|---|
| `yfinance` current version | `pip index versions yfinance` | **1.7.0** — pinned in `pyproject.toml` |
| `pandas_market_calendars` current version + NSE support | `pip install` + `mcal.get_calendar_names()` | **5.4.0**, includes `'XNSE'`, `'NSE'`, `'BSE'`, `'XBSE'` calendars |
| `XNSE` calendar session hours | `mcal.get_calendar('XNSE').schedule(...)` for Jan 2026 | Open 03:45 UTC / Close 10:00 UTC = **09:15 / 15:30 IST** |
| `yfinance.download()`'s `end` parameter semantics | Installed 1.7.0's own docstring (`help(yf.download)`) | Confirmed **exclusive**: *"for end='2023-01-01', the last data point will be on '2022-12-31'"* — matches the refactor brief's Section 15 warning exactly; `data/yfinance.py` compensates by adding one day internally |
| `yfinance.download()`'s `auto_adjust` default | Same docstring | Default is `True` in 1.7.0 — this provider deliberately overrides to `False` (see `data/yfinance.py` docstring) |

## Verified via web search, 2026-09-23

| Claim | Source(s) | Result |
|---|---|---|
| NSE cash-equity regular trading session hours | General web search on NSE trading hours | 09:15–15:30 IST, Mon–Fri excluding NSE holidays — consistent with the `XNSE` calendar check above |
| NSE bhavcopy/UDiFF delivery is actively changing | NSE circulars found via search: `NSE/MSD/74764` (18-Jun-2026), `NSE/MSD/75001` (02-Jul-2026), `NSE/MSD/75910` (24-Aug-2026), `NSE/EGR/76278` (10-Sep-2026) — all titled "Streamlining EOD information dissemination related to Bhavcopy" or similar | These circulars describe an active migration of bhavcopy file delivery to trading MEMBERS via Extranet/FTP, with further changes effective **October 12, 2026**. **Important caveat:** these circulars concern the *member-facing* Extranet channel, not necessarily the *public retail* `archives.nseindia.com` website download that `universe/current.py`'s NIFTY-200-list fetch and a future `data/nse.py` bhavcopy fetch would use — but they are strong, current evidence that NSE's data-dissemination mechanisms are genuinely in flux right now, exactly the caution brief Section 14 asks for. |

## Explicitly NOT verified (and why)

- **The exact current public bhavcopy CSV/ZIP URL and column schema** used by
  `data/nse.py`. Web search did not surface the specific public retail
  download URL (as opposed to the member Extranet paths above), and
  `nseindia.com` could not be fetched directly in this environment. Per brief
  Section 100 ("do not invent URLs or endpoints"), `data/nse.py` does **not**
  guess one — `NSEBhavcopyProvider.endpoint_template` is left `None` and
  raises a clear, actionable error if used before being configured. **Action
  required before production use of the NSE provider:** visit
  https://www.nseindia.com/all-reports, confirm the current UDiFF Common
  Bhavcopy Final CSV/ZIP naming convention, and wire it into
  `data/nse.py`.
- **The `ind_nifty200list.csv` universe URL** (`universe/current.py`,
  `configs/default.yaml: universe.source_csv_url`) — this is unchanged from
  the SOURCE NOTEBOOK's own Cell 8 (i.e., it is preserved, not newly
  invented, per the "preserve unless there's a bug" rule), but it was NOT
  re-verified as still live in this environment either. `fetch_current_nifty200`
  fails loudly (`ABORT_UNIVERSE_FETCH`) rather than silently substituting a
  stale/synthetic list if this URL has moved.
- **Current STT/GST/SEBI/brokerage/stamp-duty rates** (`configs/default.yaml:
  costs`) — unchanged PLACEHOLDER_UNVERIFIED values from the source notebook
  (brief Section 45 explicitly required confirming these against an
  authoritative current source, which was not done; see
  `RESEARCH_LIMITATIONS.md`).
- **Whether `pandas_market_calendars`'s `XNSE` calendar correctly captures
  Muhurat Trading and other irregular special sessions.** A spot-check (Nov
  2026) suggested the library's calendar does not surface a distinct Saturday
  Muhurat session as a trading day — plausible, since Muhurat is a short
  evening ceremonial session announced close to the date and not always
  modeled by generic calendar libraries the same way as regular sessions.
  `calendar/nse.py`'s `special_session_overrides` mechanism exists specifically
  so an operator can inject the correct date from an official NSE circular
  each year; it ships **empty** — no Muhurat dates are hardcoded/guessed.

## Recommended before first production run

1. Confirm the NIFTY 200 CSV URL is still live: `ema-scanner validate-data`
   (or a manual `curl`/browser check of the URL in `configs/default.yaml`).
2. Confirm/replace the NSE bhavcopy endpoint in `data/nse.py`, or keep
   `primary_provider: YFINANCE` (the default in this build) until you do.
3. Confirm current transaction cost rates against your broker.
4. If trading around Diwali/Muhurat, manually populate
   `NSECalendar.special_session_overrides` from that year's official NSE
   circular.
