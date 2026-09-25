# Data Model

## Raw -> normalized -> research pipeline (brief Section 22)

```
provider raw data (yfinance / NSE bhavcopy — provider-specific columns)
  -> data/base.ProviderMetadata attached (source, endpoint, retrieval time,
     coverage, schema/parser version)
  -> data/cache.DataCache: incremental merge, dedupe (new wins), sort,
     atomic write, metadata sidecar (.meta.json) with a content hash
  -> data/quality.validate_ohlc: PASS/WARN/FAIL + itemized issues, never
     silently deletes rows
  -> data/normalization.normalize_provider_frame: price_mode applied
     (RAW / SPLIT_ADJUSTED / TOTAL_RETURN_ADJUSTED — see below)
  -> strategy/signal_engine.build_stock_feature_frame: the research dataset
```

## Price modes

- **RAW**: provider's Open/High/Low/Close as-is.
- **SPLIT_ADJUSTED** (default): if the provider supplies an adjusted-close
  column (yfinance's `AdjClose`), Open/High/Low/Close are rescaled by the
  `AdjClose/Close` ratio so all four series share one consistent adjusted
  basis. This uses `AdjClose` purely as a SPLIT-adjustment factor.
- **TOTAL_RETURN_ADJUSTED**: **not implemented** — would require a dividend
  reinvestment model neither the source notebook nor this refactor builds;
  calling code gets a clear `NotImplementedError`, not a silent fallback.

Which mode is active is recorded in `configs/default.yaml: data.price_mode`
and flows into the run manifest — never left to a provider default.

## Cache layout

```
data/cache/{provider}__{symbol}__{frequency}__{adjustment_mode}.parquet
data/cache/{provider}__{symbol}__{frequency}__{adjustment_mode}.meta.json
```

Metadata sidecar: `retrieved_at`, `source`, `endpoint`, `coverage_start/end`,
`row_count`, `hash` (of the full cached series), `schema_version`,
`parser_version`. Writes are atomic (`tempfile` + `os.replace`) so a crash
mid-write can never corrupt the cache.

## Key column groups in a built feature frame

| Group | Example columns |
|---|---|
| OHLCV | `Open, High, Low, Close, Volume` |
| Daily EMA / state | `EMA10, EMA20, EMA89, EMA200, Daily_State` |
| Weekly EMA / state | `EMA10_W..EMA200_W, Weekly_State, Weekly_Period_End` |
| Crossovers | `BULL_X_EMA10_EMA20, BEAR_X_EMA10_EMA20, ...` (6 pairs x 2 directions) |
| Cluster | `Cluster_Width_Pct, Cluster_Center, Cluster_Max/Min, Cluster_Width_Percentile, Cluster_Expansion_State` |
| Definitions A-D | `DefA_SequentialCrossover ... DefD_CompressionExpansion` |
| Volatility | `ATR14, ATR_Pct, EMA*_Slope_Pct_10D` |
| Swings | `Is_Swing_Low/High, Swing_Low/High_Confirmed_At` |
| Pullback | `Pullback_State` |
| Entries A-E | `EntryA_FreshAlignment ... EntryE_ReclaimAfterPullback, Any_Entry_Triggered` |
| Risk | `Swing_Low_Stop, Swing_High_Stop, Stop_Distance_Pct_Long, ATR_Based_Stop_Long` |
| Regime/RS/liquidity | `Market_Regime, RS_20D/60D/120D, Volume20/50, Average_Daily_Traded_Value` |
| Signal state | `Signal_State` (see `strategy/state_machine.py` for precedence) |

Every column's precise definition traces to `STRATEGY_SPEC.md` and
`NOTEBOOK_AUDIT.md` — this table is an index, not the source of truth.
