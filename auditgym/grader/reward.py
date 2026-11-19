"""Metrics and terminal reward (case §05, DESIGN.md §5).

    P  = TP / (TP + FP)          (0 if the denominator is 0)
    R  = TP / (TP + FN)          (0 if the denominator is 0)
    F1 = 2TP / (2TP + FP + FN)   with: empty truth + empty findings -> F1 = 1
                                       empty truth + any finding    -> F1 = 0
    reward = clip(2 * F1 - 1 - 0.002 * inspection_steps, -1, 1)

``inspection_steps`` = steps taken before ``submit``, not counting the submit itself
(on truncation: all steps taken). Arithmetic is exact (``Fraction``) and converted to
``float`` once, so equal inputs always give bit-identical rewards.
"""

from __future__ import annotations

from fractions import Fraction

from .constants import REWARD_MAX, REWARD_MIN, STEP_COST

_STEP_COST = Fraction(STEP_COST)


def _ratio(num: int, den: int) -> Fraction:
    return Fraction(num, den) if den else Fraction(0)


def metrics(tp: int, fp: int, fn: int) -> tuple[Fraction, Fraction, Fraction]:
    precision = _ratio(tp, tp + fp)
    recall = _ratio(tp, tp + fn)
    if tp + fn == 0:  # empty truth
        f1 = Fraction(1) if fp == 0 else Fraction(0)
    else:
        f1 = _ratio(2 * tp, 2 * tp + fp + fn)
    return precision, recall, f1


def terminal_reward(f1: Fraction, inspection_steps: int) -> float:
    steps = max(0, int(inspection_steps))
    raw = 2 * f1 - 1 - _STEP_COST * steps
    return float(min(Fraction(REWARD_MAX), max(Fraction(REWARD_MIN), raw)))
