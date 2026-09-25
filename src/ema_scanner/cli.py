"""CLI (brief Sections 69-70, 97).

    python -m ema_scanner scan [--date YYYY-MM-DD] [--config PATH]
    python -m ema_scanner backtest --start YYYY-MM-DD --end YYYY-MM-DD [--exit-rule ...]
    python -m ema_scanner event-study --start YYYY-MM-DD --end YYYY-MM-DD
    python -m ema_scanner walk-forward --start YYYY-MM-DD --end YYYY-MM-DD [--mode 1|2]
    python -m ema_scanner sensitivity
    python -m ema_scanner validate-data --symbols RELIANCE,TCS
    python -m ema_scanner show-config

The one-click EOD workflow (Section 70) lives in `_run_scan`: resolve date ->
load/refresh data -> validate calendar -> validate universe -> validate data ->
build features -> evaluate strategies -> apply filters -> build signals ->
stops/risk -> export -> manifest -> log -> summary. This CLI has NOT been
exercised end-to-end against live data in this environment (no network access
to yfinance/NSE here — see RESEARCH_LIMITATIONS.md); the wiring is real and
importable/testable, but a live `scan` run needs to be tried from an
environment with normal internet access.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import click

from ema_scanner import STRATEGY_VERSION, __version__
from ema_scanner.calendar.nse import NSECalendar
from ema_scanner.calendar.sessions import AnalysisDateError, resolve_analysis_date
from ema_scanner.config import Config, load_config
from ema_scanner.data.base import CompositeDataProvider, DataUnavailableError
from ema_scanner.data.cache import DataCache
from ema_scanner.data.normalization import normalize_provider_frame
from ema_scanner.data.quality import QUALITY_FAIL, validate_ohlc
from ema_scanner.data.yfinance import YFinanceProvider
from ema_scanner.features.regime import compute_market_regime
from ema_scanner.logging_config import configure_logging
from ema_scanner.reporting.audit import audit_config
from ema_scanner.reporting.csv import write_csv, write_parquet
from ema_scanner.reporting.excel import write_excel_report
from ema_scanner.reporting.manifest import build_run_manifest, package_versions, write_manifest
from ema_scanner.reporting.scanner import build_scanner_row, build_scanner_table
from ema_scanner.strategy.filters import apply_optional_filters
from ema_scanner.strategy.signal_engine import build_stock_feature_frame
from ema_scanner.universe.current import UniverseFetchError, fetch_current_nifty200
from ema_scanner.universe.historical import label_universe_mode


@click.group()
@click.version_option(__version__)
def main() -> None:
    """NIFTY 200 EMA-cluster EOD scanner and research CLI."""


@main.command("show-config")
@click.option("--config", "config_path", default=None, type=click.Path(exists=True))
def show_config(config_path: str | None) -> None:
    cfg = load_config(config_path)
    click.echo(cfg.model_dump_json(indent=2))
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
        resolution = resolve_analysis_date(calendar, manual_date=manual_date)
    except AnalysisDateError as e:
        click.secho(f"ABORT: {e}", fg="red")
        sys.exit(1)
    click.echo(f"Resolved NSE analysis date: {resolution.resolved_signal_date.date()}  ({resolution.reason})")

    try:
        constituents, universe_meta = fetch_current_nifty200(cfg.universe.source_csv_url, cfg.universe.min_expected_constituents)
    except UniverseFetchError as e:
        click.secho(f"ABORT_UNIVERSE_FETCH: {e}", fg="red")
        sys.exit(1)
    universe_mode = label_universe_mode(point_in_time_provider=None)
    click.echo(f"Universe: {len(constituents)} constituents (UNIVERSE_MODE={universe_mode})")
    if universe_limit:
        constituents = constituents[:universe_limit]

    provider = CompositeDataProvider([YFinanceProvider()])
    cache = DataCache(root=str(Path("data") / "cache"))

    start_date = (resolution.resolved_signal_date - _years(cfg.data.min_history_years)).date().isoformat()
    end_date = resolution.resolved_signal_date.date().isoformat()

    try:
        index_raw, _ = provider.get_daily_ohlcv("^NSEI", start_date, end_date)
    except DataUnavailableError as e:
        click.secho(f"ABORT_BENCHMARK: {e}", fg="red")
        sys.exit(1)
    index_df = normalize_provider_frame(index_raw, cfg.data.price_mode)
    regime_df = compute_market_regime(index_df)

    rows, failures, quality_summary = [], [], {"PASS": 0, "WARN": 0, "FAIL": 0}
    for c in constituents:
        try:
            raw, meta = provider.get_daily_ohlcv(c.symbol, start_date, end_date)
            df = normalize_provider_frame(raw, cfg.data.price_mode)
            cache.write_merged(provider.name, c.symbol, df, meta)
            report = validate_ohlc(df, calendar, as_of_date=resolution.resolved_signal_date, max_stale_sessions=cfg.data.max_stale_sessions)
            quality_summary[report.status] = quality_summary.get(report.status, 0) + 1
            if report.status == QUALITY_FAIL:
                failures.append(c.symbol)
                continue
            feats = build_stock_feature_frame(df, index_df["Close"], regime_df, cfg)
            feats = apply_optional_filters(feats, cfg.strategy.liquidity)
            if feats.empty or resolution.resolved_signal_date not in feats.index:
                continue
            row = build_scanner_row(c.symbol, c.company_name, feats.loc[:resolution.resolved_signal_date], report.status)
            rows.append(row)
        except DataUnavailableError as e:
            logger.warning(f"symbol={c.symbol} stage=data_fetch status=failed error={e}")
            failures.append(c.symbol)
        except Exception as e:  # noqa: BLE001 - one symbol's pipeline failure must not abort the whole 200-stock scan (brief Section 67)
            logger.warning(f"symbol={c.symbol} stage=pipeline status=failed error={e}")
            failures.append(c.symbol)

    table = build_scanner_table(rows)
    ds = resolution.resolved_signal_date.strftime("%Y%m%d")
    out_dir = Path(output_dir)
    write_csv(table, out_dir / "signals" / f"signals_{ds}.csv")
    write_parquet(table, out_dir / "signals" / f"signals_{ds}.parquet")
    write_excel_report({"Live_Signals": table}, out_dir / "signals" / f"signals_{ds}.xlsx")

    manifest = build_run_manifest(
        analysis_date=str(resolution.resolved_signal_date.date()), analysis_timezone=cfg.calendar.timezone,
        calendar_source=calendar.calendar_source, calendar_version=calendar.calendar_version,
        universe_source=cfg.universe.source_csv_url, universe_date=universe_meta.get("universe_retrieval_date"),
        universe_mode=universe_mode, data_provider=provider.name, provider_version=None,
        package_versions=package_versions(), config_hash=cfg.config_hash(), strategy_version=STRATEGY_VERSION,
        code_version=None, rows_downloaded=len(constituents), rows_validated=len(rows),
        tickers_requested=len(constituents), tickers_processed=len(rows), tickers_failed=len(failures),
        missing_sessions=0, stale_symbols=failures, data_quality_summary=quality_summary,
        runtime_seconds=time.time() - t0,
    )
    write_manifest(manifest, out_dir / "manifests" / f"run_manifest_{ds}.json")

    click.echo(f"Stocks requested: {len(constituents)}  Successful: {len(rows)}  Failed: {len(failures)}")
    click.echo(f"Data quality: {quality_summary}")
    click.echo(f"Signals found: {len(table)}")
    click.echo(f"Runtime: {time.time() - t0:.1f}s  Output dir: {out_dir}")


@main.command("validate-data")
@click.option("--symbols", default="RELIANCE,TCS,INFY", help="Comma-separated NSE symbols")
@click.option("--config", "config_path", default=None, type=click.Path(exists=True))
def validate_data(symbols: str, config_path: str | None) -> None:
    cfg = load_config(config_path)
    calendar = NSECalendar()
    provider = CompositeDataProvider([YFinanceProvider()])
    resolution = resolve_analysis_date(calendar)
    start = (resolution.resolved_signal_date - _years(1)).date().isoformat()
    end = resolution.resolved_signal_date.date().isoformat()
    for sym in symbols.split(","):
        sym = sym.strip()
        try:
            raw, _meta = provider.get_daily_ohlcv(sym, start, end)
            df = normalize_provider_frame(raw, cfg.data.price_mode)
            report = validate_ohlc(df, calendar, as_of_date=resolution.resolved_signal_date, max_stale_sessions=cfg.data.max_stale_sessions)
            click.echo(f"{sym}: status={report.status} rows={len(df)} issues={report.issues}")
        except DataUnavailableError as e:
            click.secho(f"{sym}: DATA_UNAVAILABLE — {e}", fg="red")


def _load_universe_frames(symbols: list[str], start: str, end: str, cfg: Config):
    """Shared helper for backtest/event-study/walk-forward/sensitivity commands."""
    provider = CompositeDataProvider([YFinanceProvider()])
    index_raw, _ = provider.get_daily_ohlcv("^NSEI", start, end)
    index_df = normalize_provider_frame(index_raw, cfg.data.price_mode)
    regime_df = compute_market_regime(index_df)
    frames = {}
    for sym in symbols:
        try:
            raw, _ = provider.get_daily_ohlcv(sym, start, end)
            df = normalize_provider_frame(raw, cfg.data.price_mode)
            frames[sym] = build_stock_feature_frame(df, index_df["Close"], regime_df, cfg)
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
    click.echo(f"UNIVERSE_MODE={label_universe_mode(None)} (see docs/NOTEBOOK_AUDIT.md §2)")
    frames, _, _ = _load_universe_frames(sym_list, start, end, cfg)
    ev = run_event_study_all_models(frames, calendar, cfg.costs)
    out = Path(output_dir)
    write_csv(ev, out / "event_study_raw.csv")
    write_csv(comparison_table(ev), out / "strategy_summary.csv")
    write_csv(regime_breakdown(ev), out / "strategy_regime_breakdown.csv")
    write_csv(stock_concentration_check(ev), out / "strategy_overlap_analysis.csv")
    click.echo(f"Event study complete: {len(ev)} events across {ev['Ticker'].nunique() if not ev.empty else 0} stocks. Output: {out}")


@main.command("backtest")
@click.option("--start", required=True)
@click.option("--end", required=True)
@click.option("--symbols", default=None)
@click.option("--exit-rule", default="STOP_ONLY_RESEARCH", type=click.Choice(["STOP_ONLY_RESEARCH", "FIXED_HORIZON"]))
@click.option("--entry-model", default="Any_Entry_Triggered")
@click.option("--config", "config_path", default=None, type=click.Path(exists=True))
@click.option("--output-dir", default="outputs/research", type=click.Path())
def backtest_cmd(start: str, end: str, symbols: str | None, exit_rule: str, entry_model: str, config_path: str | None, output_dir: str) -> None:
    from ema_scanner.research.backtest import run_portfolio_backtest

    cfg = load_config(config_path)
    calendar = NSECalendar()
    sym_list = symbols.split(",") if symbols else [c.symbol for c in fetch_current_nifty200(cfg.universe.source_csv_url)[0]]
    click.echo(f"UNIVERSE_MODE={label_universe_mode(None)} (see docs/NOTEBOOK_AUDIT.md §2)")
    frames, _, _ = _load_universe_frames(sym_list, start, end, cfg)
    result = run_portfolio_backtest(frames, calendar, cfg, entry_model_col=entry_model, exit_rule=exit_rule)  # type: ignore[arg-type]  # click.Choice already restricts exit_rule's runtime values
    out = Path(output_dir)
    write_csv(result.trade_log_df(), out / "trade_log.csv")
    write_csv(result.equity_curve.reset_index(), out / "portfolio_equity.csv")
    click.echo(f"Backtest complete: {len(result.trades)} trades, final cash {result.final_cash:,.0f}. Output: {out}")


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
        provider = CompositeDataProvider([YFinanceProvider()])
        raw_frames = {}
        for sym in sym_list:
            try:
                raw, _ = provider.get_daily_ohlcv(sym, start, end)
                raw_frames[sym] = normalize_provider_frame(raw, cfg.data.price_mode)
            except DataUnavailableError:
                continue
        index_raw, _ = provider.get_daily_ohlcv("^NSEI", start, end)
        index_df = normalize_provider_frame(index_raw, cfg.data.price_mode)
        param_grid = {"fast": (10,), "medium": (20,), "structural": (89,), "long": (180, 200, 220)}
        result = true_walk_forward(raw_frames, index_df, cfg, calendar, param_grid, train_years=cfg.research.walk_forward.train_years, test_years=cfg.research.walk_forward.test_years)
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
    provider = CompositeDataProvider([YFinanceProvider()])
    raw_frames = {}
    for sym in sym_list:
        try:
            raw, _ = provider.get_daily_ohlcv(sym, start, end)
            raw_frames[sym] = normalize_provider_frame(raw, cfg.data.price_mode)
        except DataUnavailableError:
            continue
    index_raw, _ = provider.get_daily_ohlcv("^NSEI", start, end)
    index_df = normalize_provider_frame(index_raw, cfg.data.price_mode)
    grid = ema_period_sensitivity(raw_frames, index_df, cfg, calendar)
    write_csv(grid, Path(output_dir) / "strategy_parameter_sensitivity.csv")
    summary = plateau_summary(grid, "avg_return_pct", ["fast", "medium", "structural", "long"])
    click.echo(f"Sensitivity grid complete ({len(grid)} rows). Plateau summary: {summary}")
    click.secho("Reminder: this identifies whether the strategy is robust across nearby parameters — it is NOT a search for the best parameters (brief Section 58).", fg="yellow")


def _years(n: float):
    import pandas as pd
    return pd.DateOffset(years=n)


if __name__ == "__main__":
    main()
