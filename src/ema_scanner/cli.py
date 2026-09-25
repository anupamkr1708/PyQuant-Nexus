"""CLI (brief Sections 69-70, 97; Phase-2 Sections 2, 3, 6, 9, 10, 18, 22, 28).

    python -m ema_scanner scan [--date YYYY-MM-DD] [--config PATH]
    python -m ema_scanner backtest --start YYYY-MM-DD --end YYYY-MM-DD [--exit-rule ...]
    python -m ema_scanner event-study --start YYYY-MM-DD --end YYYY-MM-DD
    python -m ema_scanner walk-forward --start YYYY-MM-DD --end YYYY-MM-DD [--mode 1|2]
    python -m ema_scanner sensitivity
    python -m ema_scanner validate-data --symbols RELIANCE,TCS
    python -m ema_scanner cross-check-data --symbols RELIANCE,TCS
    python -m ema_scanner show-config

**Phase-2 rewrite -- every data-fetching command now goes through:**
    `data.factory.build_data_provider(cfg.data)`  (Section 3: config actually
        controls which provider graph is used, not a hard-coded YFinanceProvider)
    `data.repository.DataRepository`               (Section 2: cache-first,
        not "download everything every run")
    `research.warmup.calculate_required_warmup`     (Section 9: enough prior
        history is fetched so EMA200/weekly-EMA200/cluster percentiles aren't
        computed from a cold start at the requested window boundary)

This CLI has NOT been exercised end-to-end against live data in this
environment (no network access to yfinance/NSE here -- see
RESEARCH_LIMITATIONS.md); the wiring is real and importable/testable, but a
live `scan` run needs to be tried from an environment with normal internet
access.
"""
from __future__ import annotations

import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import click
import pandas as pd

from ema_scanner import STRATEGY_VERSION, __version__
from ema_scanner.calendar.nse import NSECalendar
from ema_scanner.calendar.sessions import AnalysisDateError, resolve_analysis_date
from ema_scanner.config import Config, load_config
from ema_scanner.data.base import DataUnavailableError
from ema_scanner.data.cache import DataCache
from ema_scanner.data.factory import build_data_provider
from ema_scanner.data.quality import QUALITY_FAIL, validate_ohlc
from ema_scanner.data.repository import DataRepository
from ema_scanner.features.regime import compute_market_regime
from ema_scanner.features.relative_strength import compute_universe_rs_percentile
from ema_scanner.logging_config import configure_logging
from ema_scanner.models import SymbolFailure
from ema_scanner.reporting.audit import audit_config
from ema_scanner.reporting.csv import write_csv, write_parquet
from ema_scanner.reporting.excel import write_excel_report
from ema_scanner.reporting.manifest import build_run_manifest, package_versions, write_manifest
from ema_scanner.reporting.scanner import build_scanner_row, build_scanner_tables
from ema_scanner.research.warmup import calculate_required_warmup
from ema_scanner.strategy.filters import apply_optional_filters
from ema_scanner.strategy.signal_engine import build_stock_feature_frame
from ema_scanner.universe.current import UniverseFetchError, fetch_current_nifty200
from ema_scanner.universe.historical import label_universe_mode


def _git_info() -> tuple[str | None, bool | None]:
    try:
        commit = subprocess.check_output(["git", "rev-parse", "HEAD"], stderr=subprocess.DEVNULL, cwd=Path(__file__).resolve().parents[2]).decode().strip()
        dirty = bool(subprocess.check_output(["git", "status", "--porcelain"], stderr=subprocess.DEVNULL, cwd=Path(__file__).resolve().parents[2]).decode().strip())
        return commit, dirty
    except Exception:  # noqa: BLE001 - git metadata is best-effort, never blocks a run
        return None, None


@click.group()
@click.version_option(__version__)
def main() -> None:
    """NIFTY 200 EMA-cluster EOD scanner and research CLI."""


@main.command("show-config")
@click.option("--config", "config_path", default=None, type=click.Path(exists=True))
def show_config(config_path: str | None) -> None:
    from ema_scanner.strategy.parameter_registry import classify_all

    cfg = load_config(config_path)
    click.echo(cfg.model_dump_json(indent=2))
    click.echo("\nParameter classification (Phase-2 Section 23):")
    for path, category in sorted(classify_all().items()):
        click.echo(f"  {path}: {category}")
    for w in audit_config(cfg):
        click.secho(f"WARNING: {w}", fg="yellow")


@main.command("scan")
@click.option("--date", "manual_date", default=None, help="Manual historical date YYYY-MM-DD. Omit for automatic EOD mode.")
@click.option("--config", "config_path", default=None, type=click.Path(exists=True))
@click.option("--output-dir", default="outputs", type=click.Path())
@click.option("--universe-limit", default=None, type=int, help="Debug/testing only: cap the number of symbols scanned.")
def scan(manual_date: str | None, config_path: str | None, output_dir: str, universe_limit: int | None) -> None:
    """The one-click EOD workflow (brief Section 70, 97)."""
    t0 = time.time()
    cfg = load_config(config_path)
    logger = configure_logging(str(Path(output_dir) / "logs" / "run.log"))
    for w in audit_config(cfg):
        logger.warning(w)

    calendar = NSECalendar()
    try:
        resolution = resolve_analysis_date(calendar, manual_date=manual_date, eod_data_cutoff=cfg.calendar.eod_data_cutoff)
    except AnalysisDateError as e:
        click.secho(f"ABORT: {e}", fg="red")
        sys.exit(1)
    analysis_date = resolution.resolved_signal_date
    click.echo(f"Resolved NSE analysis date: {analysis_date.date()}  ({resolution.reason})")

    try:
        constituents, universe_meta = fetch_current_nifty200(cfg.universe.source_csv_url, cfg.universe.min_expected_constituents)
    except UniverseFetchError as e:
        click.secho(f"ABORT_UNIVERSE_FETCH: {e}", fg="red")
        sys.exit(1)
    universe_mode = label_universe_mode(point_in_time_provider=None)
    click.echo(f"Universe: {len(constituents)} constituents (UNIVERSE_MODE={universe_mode})")
    if universe_limit:
        constituents = constituents[:universe_limit]

    provider = build_data_provider(cfg.data)  # Phase-2 Section 3: config-driven, not hard-coded
    cache = DataCache(root=str(Path("data") / "cache"))
    repo = DataRepository(provider, cache, price_mode=cfg.data.price_mode, overlap_sessions=cfg.data.refresh_overlap_sessions)

    warmup = calculate_required_warmup(cfg)  # Phase-2 Section 9
    requested_start = analysis_date - pd.DateOffset(years=cfg.data.min_history_years)
    fetch_start = warmup.warmup_start_via_calendar(requested_start, calendar)
    fetch_start_str, fetch_end_str = str(fetch_start.date()), str(analysis_date.date())

    try:
        index_df, _index_diag = repo.get_daily_ohlcv("^NSEI", fetch_start_str, fetch_end_str)
    except DataUnavailableError as e:
        click.secho(f"ABORT_BENCHMARK: {e}", fg="red")
        sys.exit(1)
    if analysis_date not in index_df.index:
        click.secho(
            f"ABORT_BENCHMARK: DATA_NOT_READY -- benchmark has no bar for the resolved analysis "
            f"date {analysis_date.date()} (brief Phase-2 Section 6/7).", fg="red",
        )
        sys.exit(1)
    regime_df = compute_market_regime(index_df)

    rows, failures, quality_summary = [], [], {"PASS": 0, "WARN": 0, "FAIL": 0}
    feature_frames_for_rs: dict[str, pd.DataFrame] = {}
    rows_downloaded_total, missing_sessions_total = 0, 0

    for c in constituents:
        try:
            df, diag = repo.get_daily_ohlcv(c.symbol, fetch_start_str, fetch_end_str)
            rows_downloaded_total += diag.rows_downloaded
            report = validate_ohlc(df, calendar, as_of_date=analysis_date, max_stale_sessions=cfg.data.max_stale_sessions)
            quality_summary[report.status] = quality_summary.get(report.status, 0) + 1
            missing_sessions_total += report.missing_expected_sessions
            if report.status == QUALITY_FAIL:
                failures.append(SymbolFailure(c.symbol, "quality_gate", "; ".join(report.issues) or "FAIL"))
                continue
            # Phase-2 Section 6 -- BLOCKER: the resolved analysis date must
            # exist as an ACTUAL bar. Never silently use the previous bar.
            if not report.eligible_for_signal or report.analysis_date_bar_present is False:
                failures.append(SymbolFailure(c.symbol, "analysis_date_gate", "DATA_NOT_READY: " + "; ".join(report.issues)))
                continue
            feats = build_stock_feature_frame(df, index_df["Close"], regime_df, cfg)
            feats = apply_optional_filters(feats, cfg.strategy.liquidity)
            if feats.empty or analysis_date not in feats.index:
                failures.append(SymbolFailure(c.symbol, "pipeline", "no feature row at resolved analysis date"))
                continue
            feature_frames_for_rs[c.symbol] = feats
            row = build_scanner_row(c.symbol, c.company_name, feats.loc[:analysis_date], report.status, calendar, cfg.execution.model, report.eligible_for_signal)
            rows.append((c.symbol, row))
        except DataUnavailableError as e:
            logger.warning(f"symbol={c.symbol} stage=data_fetch status=failed error={e}")
            failures.append(SymbolFailure(c.symbol, "data_fetch", str(e)))
        except Exception as e:  # noqa: BLE001 - one symbol's pipeline failure must not abort the whole 200-stock scan (brief Section 67)
            logger.warning(f"symbol={c.symbol} stage=pipeline status=failed error={e}")
            failures.append(SymbolFailure(c.symbol, "pipeline", str(e)))

    # Phase-2 Section 10: cross-sectional RS percentile, computed ONCE across
    # the eligible universe at the analysis date, injected back per symbol.
    rs_percentile = compute_universe_rs_percentile(feature_frames_for_rs, analysis_date, rs_col="RS_60D")
    row_dicts = []
    for symbol, row in rows:
        row["RS_Percentile"] = float(rs_percentile[symbol]) if symbol in rs_percentile.index else None
        row_dicts.append(row)

    tables = build_scanner_tables(row_dicts)  # Phase-2 Section 18: universe/candidates/signals, not one ambiguous table
    ds = analysis_date.strftime("%Y%m%d")
    out_dir = Path(output_dir)
    write_csv(tables["universe_diagnostics"], out_dir / "signals" / f"universe_diagnostics_{ds}.csv")
    write_csv(tables["candidates"], out_dir / "signals" / f"candidates_{ds}.csv")
    write_csv(tables["signals"], out_dir / "signals" / f"signals_{ds}.csv")
    write_parquet(tables["signals"], out_dir / "signals" / f"signals_{ds}.parquet")
    failures_df = pd.DataFrame([vars(f) for f in failures])
    write_csv(failures_df, out_dir / "signals" / f"failures_{ds}.csv")
    write_excel_report(
        {"Signals": tables["signals"], "Candidates": tables["candidates"], "Universe_Diagnostics": tables["universe_diagnostics"], "Failures": failures_df},
        out_dir / "signals" / f"scan_report_{ds}.xlsx",
    )

    git_commit, git_dirty = _git_info()
    manifest = build_run_manifest(
        analysis_date=str(analysis_date.date()), decision_timestamp=datetime.now(timezone.utc).isoformat(),
        analysis_timezone=cfg.calendar.timezone, calendar_source=calendar.calendar_source, calendar_version=calendar.calendar_version,
        universe_source=cfg.universe.source_csv_url, universe_date=universe_meta.get("universe_retrieval_date"),
        universe_mode=universe_mode, universe_count=len(constituents),
        provider=provider.name, provider_version=None,
        package_versions=package_versions(), config_hash=cfg.config_hash(), strategy_version=STRATEGY_VERSION,
        git_commit=git_commit, git_dirty=git_dirty,
        symbols_requested=len(constituents), symbols_processed=len(rows), symbols_failed=len(failures),
        rows_downloaded=rows_downloaded_total, rows_validated=len(rows), missing_sessions=missing_sessions_total,
        stale_symbols=[f.symbol for f in failures if "stale" in f.reason.lower()],
        data_quality_counts=quality_summary, runtime_seconds=time.time() - t0,
    )
    write_manifest(manifest, out_dir / "manifests" / f"run_manifest_{ds}.json")

    click.echo(f"Stocks requested: {len(constituents)}  Successful: {len(rows)}  Failed: {len(failures)}")
    click.echo(f"Data quality: {quality_summary}")
    click.echo(f"Candidates: {len(tables['candidates'])}  ACTUAL SIGNALS: {len(tables['signals'])}")
    click.echo(f"Runtime: {time.time() - t0:.1f}s  Output dir: {out_dir}")


@main.command("validate-data")
@click.option("--symbols", default="RELIANCE,TCS,INFY", help="Comma-separated NSE symbols")
@click.option("--config", "config_path", default=None, type=click.Path(exists=True))
def validate_data(symbols: str, config_path: str | None) -> None:
    cfg = load_config(config_path)
    calendar = NSECalendar()
    provider = build_data_provider(cfg.data)
    resolution = resolve_analysis_date(calendar, eod_data_cutoff=cfg.calendar.eod_data_cutoff)
    start = (resolution.resolved_signal_date - _years(1)).date().isoformat()
    end = resolution.resolved_signal_date.date().isoformat()
    for sym in symbols.split(","):
        sym = sym.strip()
        try:
            raw, _meta = provider.get_daily_ohlcv(sym, start, end)
            from ema_scanner.data.normalization import normalize_provider_frame
            df = normalize_provider_frame(raw, cfg.data.price_mode)
            report = validate_ohlc(df, calendar, as_of_date=resolution.resolved_signal_date, max_stale_sessions=cfg.data.max_stale_sessions)
            click.echo(f"{sym}: status={report.status} eligible_for_signal={report.eligible_for_signal} rows={len(df)} issues={report.issues}")
        except DataUnavailableError as e:
            click.secho(f"{sym}: DATA_UNAVAILABLE -- {e}", fg="red")


@main.command("cross-check-data")
@click.option("--symbols", required=True, help="Comma-separated NSE symbols")
@click.option("--start", required=True)
@click.option("--end", required=True)
@click.option("--config", "config_path", default=None, type=click.Path(exists=True))
@click.option("--output-dir", default="outputs/research", type=click.Path())
def cross_check_data(symbols: str, start: str, end: str, config_path: str | None, output_dir: str) -> None:
    """Phase-2 Section 28: explicit cross-source data validation. Compares
    OHLCV between the configured primary and secondary providers. Does NOT
    require exact equality (adjustment conventions can legitimately differ)
    -- reports percentage differences for manual review."""
    from ema_scanner.data.factory import build_single_provider
    from ema_scanner.data.normalization import normalize_provider_frame

    cfg = load_config(config_path)
    primary = build_single_provider(cfg.data.primary_provider)
    secondary = build_single_provider(cfg.data.secondary_provider)
    rows = []
    for sym in symbols.split(","):
        sym = sym.strip()
        try:
            raw_a, _ = primary.get_daily_ohlcv(sym, start, end)
            df_a = normalize_provider_frame(raw_a, cfg.data.price_mode)
        except (DataUnavailableError, NotImplementedError) as e:
            click.secho(f"{sym}: primary provider ({primary.name}) unavailable -- {e}", fg="yellow")
            continue
        try:
            raw_b, _ = secondary.get_daily_ohlcv(sym, start, end)
            df_b = normalize_provider_frame(raw_b, cfg.data.price_mode)
        except (DataUnavailableError, NotImplementedError) as e:
            click.secho(f"{sym}: secondary provider ({secondary.name}) unavailable -- {e}", fg="yellow")
            continue
        common_dates = df_a.index.intersection(df_b.index)
        for d in common_dates:
            for col in ("Open", "High", "Low", "Close"):
                a, b = float(df_a.loc[d, col]), float(df_b.loc[d, col])
                diff_pct = abs(a - b) / a * 100.0 if a else float("nan")
                rows.append({
                    "symbol": sym, "date": d, "field": col, "source_a": primary.name, "source_b": secondary.name,
                    "value_a": a, "value_b": b, "diff_pct": diff_pct,
                    "status": "MATCH" if diff_pct < 0.5 else "DIFFERS",
                })
    report = pd.DataFrame(rows)
    write_csv(report, Path(output_dir) / "data_crosscheck_report.csv")
    n_differs = int((report["status"] == "DIFFERS").sum()) if not report.empty else 0
    click.echo(f"Cross-check complete: {len(report)} field-date comparisons, {n_differs} flagged as DIFFERS (>0.5%). Output: {output_dir}")


def _load_universe_frames(symbols: list[str], start: str, end: str, cfg: Config):
    """Shared helper for backtest/event-study/walk-forward/sensitivity
    commands. Phase-2: goes through the provider factory + cache-first
    repository + warm-up engine, same as `scan`."""
    calendar = NSECalendar()
    provider = build_data_provider(cfg.data)
    cache = DataCache(root=str(Path("data") / "cache"))
    repo = DataRepository(provider, cache, price_mode=cfg.data.price_mode, overlap_sessions=cfg.data.refresh_overlap_sessions)

    warmup = calculate_required_warmup(cfg)
    requested_start = pd.Timestamp(start)
    fetch_start = warmup.warmup_start_via_calendar(requested_start, calendar)

    index_df, _ = repo.get_daily_ohlcv("^NSEI", str(fetch_start.date()), end)
    regime_df = compute_market_regime(index_df)
    frames = {}
    for sym in symbols:
        try:
            df, _diag = repo.get_daily_ohlcv(sym, str(fetch_start.date()), end)
            full_feats = build_stock_feature_frame(df, index_df["Close"], regime_df, cfg)
            # Trim to the REQUESTED window only after warm-up has stabilized
            # the indicators (brief Phase-2 Section 9) -- callers evaluate
            # only [requested_start, end], never the warm-up-only region.
            frames[sym] = full_feats.loc[full_feats.index >= requested_start]
        except DataUnavailableError:
            continue
    return frames, index_df, regime_df


@main.command("event-study")
@click.option("--start", required=True)
@click.option("--end", required=True)
@click.option("--symbols", default=None, help="Comma-separated symbols; default fetches current NIFTY 200")
@click.option("--config", "config_path", default=None, type=click.Path(exists=True))
@click.option("--output-dir", default="outputs/research", type=click.Path())
def event_study_cmd(start: str, end: str, symbols: str | None, config_path: str | None, output_dir: str) -> None:
    from ema_scanner.research.event_study import (
        comparison_table,
        regime_breakdown,
        run_event_study_all_models,
        stock_concentration_check,
    )

    cfg = load_config(config_path)
    calendar = NSECalendar()
    sym_list = symbols.split(",") if symbols else [c.symbol for c in fetch_current_nifty200(cfg.universe.source_csv_url)[0]]
    click.echo(f"UNIVERSE_MODE={label_universe_mode(None)} (see docs/NOTEBOOK_AUDIT.md Section 2)")
    frames, _, _ = _load_universe_frames(sym_list, start, end, cfg)
    ev = run_event_study_all_models(frames, calendar, cfg.costs)
    out = Path(output_dir)
    write_csv(ev, out / "event_study_raw.csv")
    write_csv(comparison_table(ev), out / "strategy_summary.csv")
    write_csv(regime_breakdown(ev), out / "strategy_regime_breakdown.csv")
    write_csv(stock_concentration_check(ev), out / "strategy_overlap_analysis.csv")
    click.echo(f"Event study complete: {len(ev)} events across {ev['Ticker'].nunique() if not ev.empty else 0} stocks. Output: {out}")
    click.secho("EVENT_STUDY_STATS only -- not a portfolio backtest (brief Phase-2 Section 15). Run `backtest` separately for a chronological equity curve.", fg="yellow")


@main.command("backtest")
@click.option("--start", required=True)
@click.option("--end", required=True)
@click.option("--symbols", default=None)
@click.option("--exit-rule", default=None, type=click.Choice(["STOP_ONLY_RESEARCH", "FIXED_HORIZON"]))
@click.option("--entry-model", default=None)
@click.option("--config", "config_path", default=None, type=click.Path(exists=True))
@click.option("--output-dir", default="outputs/research", type=click.Path())
def backtest_cmd(start: str, end: str, symbols: str | None, exit_rule: str | None, entry_model: str | None, config_path: str | None, output_dir: str) -> None:
    from ema_scanner.research.backtest import run_portfolio_backtest

    cfg = load_config(config_path)
    calendar = NSECalendar()
    sym_list = symbols.split(",") if symbols else [c.symbol for c in fetch_current_nifty200(cfg.universe.source_csv_url)[0]]
    click.echo(f"UNIVERSE_MODE={label_universe_mode(None)} (see docs/NOTEBOOK_AUDIT.md Section 2)")
    frames, _, _ = _load_universe_frames(sym_list, start, end, cfg)
    result = run_portfolio_backtest(frames, calendar, cfg, entry_model_col=entry_model, exit_rule=exit_rule)  # type: ignore[arg-type]
    out = Path(output_dir)
    write_csv(result.trade_log_df(), out / "trade_log.csv")
    write_csv(result.equity_curve.reset_index(), out / "portfolio_equity.csv")
    write_csv(result.skipped_signals_df(), out / "skipped_signals.csv")
    pstats = result.portfolio_stats()
    click.echo(f"Backtest complete: {len(result.trades)} trades, {len(result.skipped_signals)} skipped signals, final cash {result.final_cash:,.0f}.")
    click.echo(f"PORTFOLIO_STATS: CAGR={pstats.get('cagr_pct')}, Sharpe={pstats.get('sharpe')}, MaxDD={pstats.get('max_drawdown_pct')}. Output: {out}")


@main.command("walk-forward")
@click.option("--start", required=True)
@click.option("--end", required=True)
@click.option("--symbols", default=None)
@click.option("--mode", default="1", type=click.Choice(["1", "2"]))
@click.option("--config", "config_path", default=None, type=click.Path(exists=True))
@click.option("--output-dir", default="outputs/research", type=click.Path())
def walk_forward_cmd(start: str, end: str, symbols: str | None, mode: str, config_path: str | None, output_dir: str) -> None:
    from ema_scanner.research.walk_forward import true_walk_forward, walk_forward_fixed_spec

    cfg = load_config(config_path)
    calendar = NSECalendar()
    sym_list = symbols.split(",") if symbols else [c.symbol for c in fetch_current_nifty200(cfg.universe.source_csv_url)[0]]
    if mode == "1":
        frames, _, _ = _load_universe_frames(sym_list, start, end, cfg)
        result = walk_forward_fixed_spec(frames, calendar, cfg.costs, train_years=cfg.research.walk_forward.train_years, test_years=cfg.research.walk_forward.test_years)
    else:
        _load_universe_frames(sym_list[:1], start, end, cfg)  # warms the shared data cache before the raw-frame fetch below
        provider = build_data_provider(cfg.data)
        cache = DataCache(root=str(Path("data") / "cache"))
        repo = DataRepository(provider, cache, price_mode=cfg.data.price_mode, overlap_sessions=cfg.data.refresh_overlap_sessions)
        warmup = calculate_required_warmup(cfg)
        fetch_start = warmup.warmup_start_via_calendar(pd.Timestamp(start), calendar)
        raw_frames = {}
        for sym in sym_list:
            try:
                df, _ = repo.get_daily_ohlcv(sym, str(fetch_start.date()), end)
                raw_frames[sym] = df
            except DataUnavailableError:
                continue
        index_full, _ = repo.get_daily_ohlcv("^NSEI", str(fetch_start.date()), end)
        param_grid = {"fast": (10,), "medium": (20,), "structural": (89,), "long": (180, 200, 220)}
        result = true_walk_forward(raw_frames, index_full, cfg, calendar, param_grid, train_years=cfg.research.walk_forward.train_years, test_years=cfg.research.walk_forward.test_years)
        if not result.empty:
            click.secho("Mode 2: parameters are 'selected_training_parameters', NEVER 'optimal' -- OOS test-window results are reported separately and untouched by selection (brief Phase-2 Section 30).", fg="yellow")
    write_csv(result, Path(output_dir) / f"walk_forward_results_mode{mode}.csv")
    click.echo(f"Walk-forward (Mode {mode}) complete: {len(result)} fold-model rows. Output: {output_dir}")


@main.command("sensitivity")
@click.option("--start", required=True)
@click.option("--end", required=True)
@click.option("--symbols", default=None)
@click.option("--config", "config_path", default=None, type=click.Path(exists=True))
@click.option("--output-dir", default="outputs/research", type=click.Path())
def sensitivity_cmd(start: str, end: str, symbols: str | None, config_path: str | None, output_dir: str) -> None:
    from ema_scanner.research.sensitivity import ema_period_sensitivity, plateau_summary

    cfg = load_config(config_path)
    calendar = NSECalendar()
    sym_list = symbols.split(",") if symbols else [c.symbol for c in fetch_current_nifty200(cfg.universe.source_csv_url)[0]]
    provider = build_data_provider(cfg.data)
    cache = DataCache(root=str(Path("data") / "cache"))
    repo = DataRepository(provider, cache, price_mode=cfg.data.price_mode, overlap_sessions=cfg.data.refresh_overlap_sessions)
    warmup = calculate_required_warmup(cfg)
    fetch_start = warmup.warmup_start_via_calendar(pd.Timestamp(start), calendar)
    raw_frames = {}
    for sym in sym_list:
        try:
            df, _ = repo.get_daily_ohlcv(sym, str(fetch_start.date()), end)
            raw_frames[sym] = df
        except DataUnavailableError:
            continue
    index_df, _ = repo.get_daily_ohlcv("^NSEI", str(fetch_start.date()), end)
    grid = ema_period_sensitivity(raw_frames, index_df, cfg, calendar)
    write_csv(grid, Path(output_dir) / "strategy_parameter_sensitivity.csv")
    summary = plateau_summary(grid, "avg_return_pct", ["fast", "medium", "structural", "long"])
    click.echo(f"Sensitivity grid complete ({len(grid)} rows). Plateau summary: {summary}")
    click.secho("Reminder: this identifies whether the strategy is robust across nearby parameters -- it is NOT a search for the best parameters (brief Section 58).", fg="yellow")


def _years(n: float):
    return pd.DateOffset(years=n)


if __name__ == "__main__":
    main()
