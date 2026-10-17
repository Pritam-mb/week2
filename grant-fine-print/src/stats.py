"""Statistical calculations for Grant Fine Print.

Includes Wilson score confidence intervals for binomial proportions,
ensuring small sample sizes (N < 30) carry explicit uncertainty estimates.
"""

from __future__ import annotations

import math
from typing import Any, Dict, Tuple


def wilson_ci(k: int, n: int, confidence: float = 0.95) -> Tuple[float, float]:
    """Calculate the two-sided Wilson score confidence interval for a proportion.

    Parameters
    ----------
    k : int
        Number of successes / positive events.
    n : int
        Total number of trials / sample size.
    confidence : float
        Confidence level, default 0.95 (95% CI).

    Returns
    -------
    Tuple[float, float]
        (lower_bound, upper_bound) as floats in [0.0, 1.0], rounded to 4 decimals.
    """
    if n <= 0:
        return (0.0, 0.0)
    k = max(0, min(k, n))
    p = k / n

    if abs(confidence - 0.95) < 0.005:
        z = 1.959963984540054
    elif abs(confidence - 0.99) < 0.005:
        z = 2.5758293035489004
    elif abs(confidence - 0.90) < 0.005:
        z = 1.6448536269514722
    else:
        z = 1.959963984540054

    z2 = z * z
    denominator = 1.0 + z2 / n
    center = p + z2 / (2.0 * n)
    spread = z * math.sqrt((p * (1.0 - p) + z2 / (4.0 * n)) / n)

    lower = max(0.0, (center - spread) / denominator)
    upper = min(1.0, (center + spread) / denominator)

    return (round(lower, 4), round(upper, 4))


def format_wilson_ci(k: int, n: int, confidence: float = 0.95) -> str:
    """Format confidence interval as: 'k of N (P%, 95% CI L% to U%)'.

    Examples
    --------
    >>> format_wilson_ci(16, 26)
    '16 of 26 (61.5%, 95% CI 42.5% to 77.6%)'
    """
    if n <= 0:
        return "0 of 0 (0.0%)"
    p = (k / n) * 100.0
    low, high = wilson_ci(k, n, confidence)
    conf_pct = int(round(confidence * 100))
    return f"{k} of {n} ({p:.1f}%, {conf_pct}% CI {low*100:.1f}% to {high*100:.1f}%)"


def compute_share_cell(
    k: int,
    n: int,
    small_sample_threshold: int = 30,
    confidence: float = 0.95,
) -> Dict[str, Any]:
    """Compute share metrics for table presentation, including CI when N < threshold.

    Returns dict with keys:
    - pct: float (e.g. 61.5)
    - k_of_n: str (e.g. '16 of 26')
    - is_small_sample: bool
    - ci_text: str (e.g. '95% CI 42.5% to 77.6%')
    - display: str
    """
    if n <= 0:
        return {
            "pct": 0.0,
            "k_of_n": "0 of 0",
            "is_small_sample": False,
            "ci_text": "",
            "display": "0 of 0 (0.0%)",
        }
    pct = round((k / n) * 100.0, 1)
    is_small = n < small_sample_threshold
    low, high = wilson_ci(k, n, confidence)
    ci_text = f"95% CI {low*100:.1f}% to {high*100:.1f}%"
    display = (
        f"{k} of {n} ({pct:.1f}%, {ci_text})"
        if is_small
        else f"{k} of {n} ({pct:.1f}%)"
    )
    return {
        "pct": pct,
        "k_of_n": f"{k} of {n}",
        "is_small_sample": is_small,
        "ci_text": ci_text if is_small else "",
        "display": display,
    }
