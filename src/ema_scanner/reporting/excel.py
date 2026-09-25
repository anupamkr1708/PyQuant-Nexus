"""Excel export (notebook Cell 46; audit row 34).

Preserves the notebook's own percent-formatting fix exactly: percentage
columns are stored as a 0-1 FRACTION in the cell, with the cell NUMBER FORMAT
set to '0.00%' — never stored as an already-multiplied-by-100 number with a
percent format applied on top (which double-scales the displayed value; this
was a bug the notebook explicitly fixed and which this refactor must not
reintroduce, per brief Section 84).

Excel is reporting-only (brief Section 85) — Parquet/CSV remain the
machine-readable layer; nothing here is read back by the pipeline.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

PCT_COLUMN_HINTS = ("_Pct", "Rate_Pct", "Return_Pct", "Slope_Pct", "Distance_Pct")


def _is_pct_column(col: str) -> bool:
    return any(h in col for h in PCT_COLUMN_HINTS)


def write_excel_report(sheets: dict[str, pd.DataFrame], path: str | Path) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        for sheet_name, df in sheets.items():
            safe_name = sheet_name[:31]
            df_to_write = df.copy()
            pct_cols = [c for c in df_to_write.columns if _is_pct_column(str(c))]
            for c in pct_cols:
                # Notebook's fix: store as fraction (divide the already-"in percent
                # points" value by 100) so Excel's '0.00%' format displays correctly.
                df_to_write[c] = pd.to_numeric(df_to_write[c], errors="coerce") / 100.0
            df_to_write.to_excel(writer, sheet_name=safe_name, index=False)
            worksheet = writer.sheets[safe_name]
            for i, col in enumerate(df_to_write.columns, start=1):
                if col in pct_cols:
                    for cell in worksheet.iter_cols(min_col=i, max_col=i, min_row=2):
                        for c in cell:
                            c.number_format = "0.00%"
