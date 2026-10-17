"""Stage 2: deterministic matching of verified conditions against a profile.

Plain code only. NOT ELIGIBLE is only possible when a verified (verbatim)
condition conflicts with the profile. Anything the code cannot evaluate
becomes CHECK, with the sentences to read.
"""

from __future__ import annotations

from .models import (
    Condition,
    ConditionType,
    EVALUABLE_TYPES,
    Polarity,
    Profile,
    Verdict,
    VerdictRow,
)

# Profile organisation types -> the Grants.gov applicant-type code values the
# profile can satisfy. "others" is deliberately included because an "Others"
# code opportunity requires reading the free text.
PROFILE_TO_CODES: dict[str, set[str]] = {
    "nonprofit": {"nonprofit_501c3", "nonprofit_non_501c3", "others"},
    "for_profit": {"for_profit", "small_business", "others"},
    "university": {
        "public_state_university",
        "private_university",
        "others",
    },
    "tribal": {
        "federally_recognized_tribal_government",
        "native_american_tribal_organization",
        "others",
    },
    "government": {
        "state_government",
        "county_government",
        "city_or_township_government",
        "special_district_government",
        "independent_school_district",
        "others",
    },
    "individual": {"individual", "others"},
    "small_business": {"small_business", "for_profit", "others"},
    "other": {"others"},
}

# Free-text condition value -> expected applicant-type code value.
ORG_TYPE_KEYWORDS: list[tuple[str, list[str]]] = [
    ("nonprofit_501c3", ["501(c)(3)", "charitable", "nonprofit"]),
    ("nonprofit_non_501c3", ["nonprofit"]),
    ("for_profit", ["for-profit", "commercial organization", "company"]),
    ("small_business", ["small business"]),
    ("public_state_university", ["public", "state university"]),
    ("private_university", ["private", "institution of higher education", "university"]),
    ("federally_recognized_tribal_government", ["federally recognized", "federally-recognized", "tribal government"]),
    ("native_american_tribal_organization", ["tribal", "native american", "indian tribe"]),
    ("state_government", ["state government", "state agency"]),
    ("county_government", ["county"]),
    ("city_or_township_government", ["city", "township", "municipal"]),
    ("individual", ["individual", "sole proprietor"]),
]


def _expected_code(value: str) -> str | None:
    v = value.lower()
    for code, keywords in ORG_TYPE_KEYWORDS:
        if any(k in v for k in keywords):
            return code
    return None


def evaluate_condition(cond: Condition, profile: Profile) -> str:
    """Return 'satisfied', 'conflict', or 'unknown'."""
    if cond.type not in EVALUABLE_TYPES:
        return "unknown"

    value = cond.value.lower()

    if cond.type == ConditionType.ORG_TYPE:
        expected = _expected_code(value)
        if expected is None:
            return "unknown"
        if cond.polarity == Polarity.EXCLUDED:
            # e.g. "for-profit organizations are excluded"
            if expected in PROFILE_TO_CODES.get(profile.org_type, set()):
                return "conflict"
            return "satisfied"
        return (
            "satisfied"
            if expected in PROFILE_TO_CODES.get(profile.org_type, set())
            else "conflict"
        )

    if cond.type == ConditionType.LOCATION:
        us_terms = ["u.s.", "united states", "usa", "u.s. based", "u.s.-based", "domestic"]
        outside_terms = ["outside the u.s", "outside the united states", "foreign", "non-u.s", "outside the us"]
        requires_us = any(t in value for t in us_terms)
        excludes_us = any(t in value for t in outside_terms)
        if excludes_us and profile.us_based:
            return "conflict"
        if requires_us and not profile.us_based:
            return "conflict"
        if requires_us and profile.us_based:
            return "satisfied"
        if excludes_us and not profile.us_based:
            return "satisfied"
        return "unknown"

    if cond.type == ConditionType.SIZE:
        if "small business" in value:
            if profile.org_type in ("small_business",) or profile.size_band in ("micro", "small"):
                return "satisfied"
            return "conflict"
        return "unknown"

    return "unknown"


def match(
    conditions: list[Condition],
    profile: Profile,
    opportunity_id: str,
    override: str | None = None,
    unverified: list[Condition] | None = None,
) -> VerdictRow:
    """Produce a VerdictRow for one opportunity-and-profile pair.

    ``conditions`` are quote-verified conditions. ``unverified`` are conditions
    the verifier dropped (missing or non-verbatim quote): they can never
    justify NOT ELIGIBLE, but per PRD 6.3 their presence forces CHECK instead
    of ELIGIBLE.
    """
    if override:
        try:
            verdict = Verdict(override)
        except ValueError:
            verdict = Verdict.CHECK
        return VerdictRow(
            opportunity_id=opportunity_id,
            profile_id=profile.id,
            verdict=verdict,
            conditions=list(conditions),
            override=override,
        )

    disqualifying: list[str] = []
    check_quotes: list[str] = []
    any_unknown = bool(unverified)

    for cond in conditions:
        result = evaluate_condition(cond, profile)
        if result == "conflict":
            if cond.quote and cond.quote not in disqualifying:
                disqualifying.append(cond.quote)
        elif result == "unknown":
            any_unknown = True
            if cond.quote and cond.quote not in check_quotes:
                check_quotes.append(cond.quote)

    if disqualifying:
        verdict = Verdict.NOT_ELIGIBLE
    elif any_unknown:
        verdict = Verdict.CHECK
    else:
        verdict = Verdict.ELIGIBLE

    return VerdictRow(
        opportunity_id=opportunity_id,
        profile_id=profile.id,
        verdict=verdict,
        disqualifying_quotes=disqualifying,
        check_quotes=check_quotes,
        conditions=list(conditions),
    )
