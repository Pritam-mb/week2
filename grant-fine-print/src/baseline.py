"""System 1: code-only baseline (no model at all).

Matches the profile's organisation type against the opportunity's
applicant-type codes. The "Others" code ("25") carries no information, so an
opportunity that offers "Others" becomes CHECK (the official facet filter
cannot answer for it).
"""

from __future__ import annotations

from typing import Any, Optional

from .config import get
from .match import PROFILE_TO_CODES
from .models import Opportunity, Profile, Verdict, VerdictRow

OTHERS_CODE = "25"


def code_only_row(
    opportunity: Opportunity,
    profile: Profile,
    config: Optional[dict[str, Any]] = None,
) -> VerdictRow:
    """Verdict from applicant-type codes alone; no free text is read."""
    raw = {str(code).strip() for code in opportunity.applicant_types}
    code_map = (config and get(config, "match.org_type_codes")) or {}
    values = {code_map.get(code, code) for code in raw}

    profile_codes = PROFILE_TO_CODES.get(profile.org_type, {"others"})
    specific = values - {"others"}
    profile_specific = profile_codes - {"others"}

    if specific and specific & profile_specific:
        verdict = Verdict.ELIGIBLE
    elif OTHERS_CODE in raw or not raw:
        # "Others" carries no information: the code filter cannot answer,
        # so a human must read the free text.
        verdict = Verdict.CHECK
    else:
        # Concrete codes exist and none matches the profile: the code filter
        # would rule this grant out for the client.
        verdict = Verdict.NOT_ELIGIBLE

    return VerdictRow(
        opportunity_id=opportunity.id,
        profile_id=profile.id,
        verdict=verdict,
        disqualifying_quotes=[],  # a code filter cannot quote a sentence
        check_quotes=[],
        conditions=[],
    )
