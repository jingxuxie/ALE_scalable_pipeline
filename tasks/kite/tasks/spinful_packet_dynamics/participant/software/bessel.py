"""Integer-order Bessel functions needed by the packet-contraction formula.

This helper intentionally depends only on the Python standard library and
NumPy.  Its accuracy target covers this task's public time interval and basis
order; it is not a general special-functions package.
"""

from __future__ import annotations

import math

import numpy as np


def bessel_j_sequence(argument: float, count: int) -> np.ndarray:
    """Return ``[J_0(argument), ..., J_(count-1)(argument)]`` as float64.

    Each order is evaluated by its power series.  The implementation handles
    negative arguments through ``J_n(-x) = (-1)^n J_n(x)`` and is stable for
    ``abs(argument) <= 12`` and ``count <= 128``.
    """

    if not isinstance(count, int) or count < 1 or count > 128:
        raise ValueError("count must be an integer in [1, 128]")
    x = float(argument)
    if not math.isfinite(x) or abs(x) > 12.0:
        raise ValueError("argument must be finite with absolute value <= 12")
    magnitude = abs(x)
    answer = np.zeros(count, dtype=np.float64)
    if magnitude == 0.0:
        answer[0] = 1.0
        return answer
    half = 0.5 * magnitude
    square_factor = -0.25 * magnitude * magnitude
    for order in range(count):
        term = math.exp(order * math.log(half) - math.lgamma(order + 1.0))
        total = term
        compensation = 0.0
        for k in range(512):
            term *= square_factor / ((k + 1.0) * (order + k + 1.0))
            corrected = term - compensation
            updated = total + corrected
            compensation = (updated - total) - corrected
            total = updated
            if abs(term) <= 2.0e-16 * max(1.0, abs(total)):
                break
        else:
            raise ArithmeticError("Bessel series failed to converge")
        if x < 0.0 and order % 2:
            total = -total
        answer[order] = total
    return answer
