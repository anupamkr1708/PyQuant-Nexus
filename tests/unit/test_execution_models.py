"""Execution model tests (brief Section 93 #17-19: next-open, next-close, same-close)."""
import pytest

from ema_scanner.calendar.nse import NSECalendar
from ema_scanner.execution.execution_models import resolve_execution_price
from tests.fixtures.synthetic import make_synthetic_ohlcv


def test_same_close_execution_uses_signal_bar_close():
    df = make_synthetic_ohlcv(50, seed=20)
    cal = NSECalendar()
    signal_date = df.index[10]
    exe = resolve_execution_price(df, signal_date, cal, execution_model="same_close")
    assert exe.execution_date == signal_date
    assert exe.execution_price == pytest.approx(df.loc[signal_date, "Close"])


def test_next_open_execution_uses_following_bar_open():
    df = make_synthetic_ohlcv(50, seed=21)
    cal = NSECalendar()
    signal_date = df.index[10]
    exe = resolve_execution_price(df, signal_date, cal, execution_model="next_open")
    next_date = df.index[11]
    assert exe.execution_date == next_date
    assert exe.execution_price == pytest.approx(df.loc[next_date, "Open"])


def test_next_close_execution_uses_following_bar_close():
    df = make_synthetic_ohlcv(50, seed=22)
    cal = NSECalendar()
    signal_date = df.index[10]
    exe = resolve_execution_price(df, signal_date, cal, execution_model="next_close")
    next_date = df.index[11]
    assert exe.execution_price == pytest.approx(df.loc[next_date, "Close"])


def test_execution_reference_label_is_not_a_fill_claim():
    df = make_synthetic_ohlcv(50, seed=23)
    cal = NSECalendar()
    exe = resolve_execution_price(df, df.index[5], cal, execution_model="next_open")
    assert exe.is_actual_fill is False
    assert exe.label == "NEXT_SESSION_EXECUTION_REFERENCE"

