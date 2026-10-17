"""Quote verification: the quote-or-abstain rule, enforced in code.

A condition may only be used to rule a profile out if its quote, after
whitespace normalisation, is a verbatim substring of the source text.
"""

from __future__ import annotations

from dataclasses import dataclass

from .models import Condition, normalize_ws


@dataclass
class VerificationResult:
    verified: list[Condition]
    dropped: list[tuple[Condition, str]]  # (condition, reason)


def is_verbatim_quote(quote: str, source: str) -> bool:
    """True if `quote` is a whitespace-normalised substring of `source`."""
    q = normalize_ws(quote)
    if not q:
        return False
    return q in normalize_ws(source)


def verify_conditions(
    conditions: list[Condition], source_text: str
) -> VerificationResult:
    verified: list[Condition] = []
    dropped: list[tuple[Condition, str]] = []

    for cond in conditions:
        if not cond.quote:
            dropped.append((cond, "empty_quote"))
            continue
        if not is_verbatim_quote(cond.quote, source_text):
            dropped.append((cond, "not_verbatim"))
            continue
        verified.append(cond)

    return VerificationResult(verified=verified, dropped=dropped)
