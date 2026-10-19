"""Shared data models for Grant Fine Print.

Everything here is stdlib-only so the core can be imported and tested
without installing third-party packages.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any, Optional


class Verdict(str, Enum):
    ELIGIBLE = "ELIGIBLE"
    NOT_ELIGIBLE = "NOT_ELIGIBLE"
    CHECK = "CHECK"


class Polarity(str, Enum):
    REQUIRED = "required"
    EXCLUDED = "excluded"


class ConditionType(str, Enum):
    ORG_TYPE = "org_type"
    LOCATION = "location"
    CITIZENSHIP_OR_RESIDENCY = "citizenship_or_residency"
    SIZE = "size"
    PRIOR_AWARD_OR_STATUS = "prior_award_or_status"
    PARTNERSHIP_REQUIRED = "partnership_required"
    COST_SHARE = "cost_share"
    OTHER = "other"


# Condition types the stage-2 matcher can evaluate directly.
EVALUABLE_TYPES = {
    ConditionType.ORG_TYPE,
    ConditionType.LOCATION,
    ConditionType.SIZE,
}


_WS_RE = re.compile(r"\s+")


def normalize_ws(text: str) -> str:
    """Collapse all whitespace runs to single spaces and strip ends.

    This is the normalisation used for verbatim-quote checks.
    """
    return _WS_RE.sub(" ", text or "").strip()


def text_hash(text: str) -> str:
    return hashlib.sha256(normalize_ws(text).encode("utf-8")).hexdigest()


@dataclass
class Condition:
    type: ConditionType
    polarity: Polarity
    value: str
    quote: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type.value,
            "polarity": self.polarity.value,
            "value": self.value,
            "quote": self.quote,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Condition":
        return cls(
            type=ConditionType(data["type"]),
            polarity=Polarity(data["polarity"]),
            value=data.get("value", ""),
            quote=data.get("quote", ""),
        )


@dataclass
class Opportunity:
    id: str
    opp_number: str
    title: str
    agency: str = ""
    status: str = ""
    open_date: str = ""
    close_date: str = ""
    award_floor: Optional[float] = None
    award_ceiling: Optional[float] = None
    award_estimate: Optional[float] = None
    cost_sharing: bool = False
    applicant_types: list[str] = field(default_factory=list)
    synopsis: str = ""
    eligibility_text: str = ""
    link: str = ""

    @property
    def source_text(self) -> str:
        """The text the eligibility rules live in."""
        parts = [p for p in (self.eligibility_text, self.synopsis) if p]
        return "\n\n".join(parts)

    @property
    def text_hash(self) -> str:
        return text_hash(self.source_text)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Opportunity":
        known = {f for f in cls.__dataclass_fields__}
        kwargs = {k: v for k, v in data.items() if k in known}
        for required in ("id", "opp_number", "title"):
            kwargs.setdefault(required, "")
        return cls(**kwargs)


@dataclass
class Profile:
    id: str
    name: str
    org_type: str = ""
    us_based: bool = True
    state: str = ""
    size_band: str = ""
    focus_keywords: list[str] = field(default_factory=list)
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Profile":
        known = {f for f in cls.__dataclass_fields__}
        kwargs = {k: v for k, v in data.items() if k in known}
        kwargs.setdefault("id", "")
        kwargs.setdefault("name", "")
        return cls(**kwargs)


@dataclass
class VerdictRow:
    """One opportunity-and-profile result."""

    opportunity_id: str
    profile_id: str
    verdict: Verdict
    # Sentences that justify a NOT_ELIGIBLE verdict (verbatim quotes).
    disqualifying_quotes: list[str] = field(default_factory=list)
    # Sentences a human must read for a CHECK verdict.
    check_quotes: list[str] = field(default_factory=list)
    # All extracted conditions, for explainability.
    conditions: list[Condition] = field(default_factory=list)
    # Human override from corrections, if any.
    override: Optional[str] = None
    # Model-proposed disqualifier quotes BEFORE quote verification
    # (measured by eval as quote_validity, before code enforcement).
    proposed_disqualifier_quotes: list[str] = field(default_factory=list)
    # Extraction latency for this opportunity in milliseconds, when known.
    latency_ms: Optional[float] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "opportunity_id": self.opportunity_id,
            "profile_id": self.profile_id,
            "verdict": self.verdict.value,
            "disqualifying_quotes": self.disqualifying_quotes,
            "check_quotes": self.check_quotes,
            "conditions": [c.to_dict() for c in self.conditions],
            "override": self.override,
            "proposed_disqualifier_quotes": self.proposed_disqualifier_quotes,
            "latency_ms": self.latency_ms,
        }
