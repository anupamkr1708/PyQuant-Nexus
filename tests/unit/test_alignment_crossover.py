"""Alignment + crossover tests (brief Section 93 #2-5)."""
import pandas as pd

from ema_scanner.features.alignment import (
    STATE_BEARISH_ALIGNED,
    STATE_BULLISH_ALIGNED,
    STATE_MIXED,
    classify_alignment,
)
from ema_scanner.features.crossover import bearish_crossover, bullish_crossover


def test_classify_alignment_bullish():
    idx = pd.RangeIndex(3)
    e10, e20, e89, e200 = pd.Series([4, 4, 4], idx), pd.Series([3, 3, 3], idx), pd.Series([2, 2, 2], idx), pd.Series([1, 1, 1], idx)
    state = classify_alignment(e10, e20, e89, e200)
    assert (state == STATE_BULLISH_ALIGNED).all()


def test_classify_alignment_bearish():
    idx = pd.RangeIndex(3)
    e10, e20, e89, e200 = pd.Series([1, 1, 1], idx), pd.Series([2, 2, 2], idx), pd.Series([3, 3, 3], idx), pd.Series([4, 4, 4], idx)
    state = classify_alignment(e10, e20, e89, e200)
    assert (state == STATE_BEARISH_ALIGNED).all()


def test_classify_alignment_mixed_when_not_strictly_ordered():
    idx = pd.RangeIndex(1)
    e10, e20, e89, e200 = pd.Series([2], idx), pd.Series([2], idx), pd.Series([1], idx), pd.Series([0], idx)
    state = classify_alignment(e10, e20, e89, e200)  # e10 == e20, not strictly >
    assert state.iloc[0] == STATE_MIXED


def test_bullish_crossover_exact_point():
    a = pd.Series([1, 1, 3, 4])
    b = pd.Series([2, 2, 2, 2])
    x = bullish_crossover(a, b)
    assert list(x) == [False, False, True, False]  # crossover=True only on the crossing bar


def test_bearish_crossover_exact_point():
    a = pd.Series([3, 3, 1, 0])
    b = pd.Series([2, 2, 2, 2])
    x = bearish_crossover(a, b)
    assert list(x) == [False, False, True, False]


def test_crossover_first_bar_is_never_true():
    a = pd.Series([5, 6, 7])
    b = pd.Series([1, 2, 3])
    assert bullish_crossover(a, b).iloc[0] == False
