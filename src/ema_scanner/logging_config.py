"""Structured logging setup (brief Section 68)."""
from __future__ import annotations

import logging
import sys


def configure_logging(log_path: str | None = None, level: int = logging.INFO) -> logging.Logger:
    logger = logging.getLogger("ema_scanner")
    logger.setLevel(level)
    logger.handlers.clear()
    fmt = logging.Formatter("%(asctime)s level=%(levelname)s logger=%(name)s %(message)s")
    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(fmt)
    logger.addHandler(console)
    if log_path:
        from pathlib import Path
        Path(log_path).parent.mkdir(parents=True, exist_ok=True)
        fh = logging.FileHandler(log_path)
        fh.setFormatter(fmt)
        logger.addHandler(fh)
    return logger
