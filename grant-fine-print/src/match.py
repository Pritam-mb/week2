"""Stage 2: deterministic matching of verified conditions against a profile.

Plain code only. NOT ELIGIBLE is only possible when a verified (verbatim)
condition conflicts with the profile. Anything the code cannot evaluate
becomes CHECK, with review reasons and any verified sentences to read.
"""

from __future__ import annotations

import re

from .source_rules import interpret_source_rule

from .models import (
    Condition,
    ConditionType,
    EVALUABLE_TYPES,
    Polarity,
    Profile,
    Verdict,
    VerdictRow,
    normalize_ws,
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
    ("nonprofit_501c3", [
        "501(c)(3)", "charitable", "nonprofit", "non-profit", "not-for-profit",
    ]),
    ("nonprofit_non_501c3", ["nonprofit"]),
    ("for_profit", ["for-profit", "commercial organization", "company"]),
    ("small_business", ["small business", "small businesses"]),
    ("public_state_university", [
        "public university", "public universities", "state university", "state universities",
    ]),
    ("private_university", [
        "private university", "institution of higher education",
        "institutions of higher education", "university", "universities",
    ]),
    ("federally_recognized_tribal_government", [
        "federally recognized tribal government", "federally-recognized tribal government",
        "tribal government",
    ]),
    ("native_american_tribal_organization", ["tribal", "native american", "indian tribe"]),
    ("state_government", ["state government", "state agency"]),
    ("county_government", ["county"]),
    ("city_or_township_government", ["city", "township", "municipal"]),
    ("individual", ["individual", "sole proprietor"]),
]

_ORG_PATTERNS = [
    (code, re.compile(r"(?<!\w)" + re.escape(keyword) + r"s?(?!\w)"))
    for code, keywords in ORG_TYPE_KEYWORDS
    for keyword in keywords
]
_US_TERM = r"(?:u\.s(?:\.a)?\.?|usa|us|united states)"
_US_RE = re.compile(r"(?<!\w)(?:" + _US_TERM + r"|domestic)(?!\w)")
_OUTSIDE_US_RE = re.compile(
    r"(?<!\w)(?:(?:outside(?: of)?(?: the)?[ -]+|non[ -]*)"
    + _US_TERM + r"|foreign|non[ -]+domestic)(?!\w)"
)


def _rule_text(text: str | None) -> str:
    return re.sub(r"[\u2010-\u2015]", "-", normalize_ws(text).lower())


def _org_codes(value: str) -> set[str]:
    """Use whole phrases, preferring specific phrases over contained keywords."""
    spans: dict[tuple[int, int], str] = {}
    for code, pattern in _ORG_PATTERNS:
        for hit in pattern.finditer(value):
            spans.setdefault(hit.span(), code)
    return {
        code for (start, end), code in spans.items()
        if not any(
            left <= start and end <= right and (left, right) != (start, end)
            for left, right in spans
        )
    }


def _expected_code(value: str) -> str | None:
    codes = _org_codes(_rule_text(value))
    return next(iter(codes)) if len(codes) == 1 else None


def _with_polarity(applies: bool | None, polarity: Polarity) -> str:
    if applies is None:
        return "unknown"
    return "satisfied" if applies == (polarity == Polarity.REQUIRED) else "conflict"


def _heuristic_result(applies: bool | None, polarity: Polarity,
                      unknown_reason: str | None = None) -> tuple[str, str | None]:
    result = _with_polarity(applies, polarity)
    if result == "conflict":
        return "unknown", "Keyword matching does not establish a complete source restriction; review applicant routes, qualifications, and exceptions in the original notice."
    return result, unknown_reason


def _is_small_business(profile: Profile) -> bool | None:
    if profile.org_type == "small_business":
        return True
    if profile.org_type == "for_profit" and profile.size_band in (
        "micro", "small", "medium", "large"
    ):
        return profile.size_band in ("micro", "small")
    return None


def _small_business_reason(profile: Profile) -> str:
    if profile.org_type not in PROFILE_TO_CODES or profile.org_type == "other":
        return "The profile's organization type is missing or unrecognized; confirm it to assess small-business status."
    if profile.org_type == "for_profit":
        return "The profile's size band is missing or unrecognized; confirm it to assess small-business status."
    return "The profile does not establish small-business status; review its organization type and size information."


def _evaluate_with_reason(cond: Condition, profile: Profile) -> tuple[str, str | None]:
    """Keep evaluation and its review explanation on the same decision path."""
    # A small whole-sentence grammar can resolve supported alternatives and
    # organizational geography without trusting model keywords alone. It never
    # invents a condition that was absent from the extraction.
    if cond.value and cond.quote and cond.polarity in (Polarity.REQUIRED, Polarity.EXCLUDED):
        interpreted = interpret_source_rule(cond, profile)
        if interpreted is not None:
            reason = (
                "The quoted rule and extracted fields or profile facts do not establish a supported match; review the original notice."
                if interpreted == "unknown" else None
            )
            return interpreted, reason
    if cond.type in (ConditionType.LOCATION, ConditionType.CITIZENSHIP_OR_RESIDENCY):
        if re.search(r"\b(?:components?|citizens?|citizenship|residency|residents?|projects?)\b",
                     _rule_text(cond.quote)):
            return "unknown", "The rule concerns components, people, or project geography; organizational U.S.-based status does not establish that fact."
    if cond.type not in EVALUABLE_TYPES:
        labels = {
            ConditionType.CITIZENSHIP_OR_RESIDENCY: "citizenship or residency",
            ConditionType.PRIOR_AWARD_OR_STATUS: "prior award or status",
            ConditionType.PARTNERSHIP_REQUIRED: "partnership",
            ConditionType.COST_SHARE: "cost sharing",
            ConditionType.OTHER: "other eligibility",
        }
        label = labels.get(cond.type)
        if label:
            return "unknown", f"The matcher cannot automatically evaluate {label} requirements; review the original notice."
        return "unknown", "The extracted condition type is unrecognized; review the original notice."
    if cond.polarity not in (
        Polarity.REQUIRED, Polarity.EXCLUDED
    ):
        return "unknown", "The rule does not specify a recognized requirement or exclusion; review the original notice."

    value = _rule_text(cond.value)
    quote = _rule_text(cond.quote)
    if not quote:
        return "unknown", "The condition has no source quote to verify; review the original notice."
    if not value:
        return "unknown", "The extracted condition has no usable rule value; review the quoted requirement."
    # The schema has no connective/group field. A shared OR/list quote cannot
    # safely turn its extracted alternatives into independent requirements.
    if re.search(r"\bor\b", value) or re.search(r"\bor\b", quote):
        return "unknown", "The rule contains OR alternatives; review which alternative applies instead of treating each as required."
    if len(_org_codes(quote)) > 1:
        return "unknown", "The source quote lists multiple organization types; review how the listed applicants are grouped."

    if cond.type == ConditionType.ORG_TYPE:
        expected = _expected_code(value)
        codes = PROFILE_TO_CODES.get(profile.org_type)
        if expected is None:
            return "unknown", "The organization-type rule is ambiguous or unrecognized; compare it with the profile in the original notice."
        if not codes or profile.org_type == "other":
            return "unknown", "The profile's organization type is missing or unrecognized; confirm it against the quoted requirement."
        if expected == "small_business":
            applies = _is_small_business(profile)
            return _heuristic_result(applies, cond.polarity, _small_business_reason(profile) if applies is None else None)
        return _heuristic_result(expected in codes, cond.polarity)

    if cond.type == ConditionType.LOCATION:
        if not isinstance(profile.us_based, bool):
            return "unknown", "The profile's U.S.-based status is missing or unrecognized; confirm its location against the quoted requirement."
        outside_us = bool(_OUTSIDE_US_RE.search(value))
        # Remove the entire non-US phrase before looking for US terms inside it.
        inside_us = bool(_US_RE.search(_OUTSIDE_US_RE.sub(" ", value)))
        if inside_us == outside_us:  # Neither recognized, or mixed geography.
            return "unknown", "The location rule is ambiguous or not a recognized U.S./non-U.S. requirement; review the geography in the original notice."
        return _heuristic_result(profile.us_based == inside_us, cond.polarity)

    if cond.type == ConditionType.SIZE:
        if re.search(r"\bsmall business(?:es)?\b", value):
            applies = _is_small_business(profile)
            return _heuristic_result(applies, cond.polarity, _small_business_reason(profile) if applies is None else None)
        return "unknown", "The size rule is not a supported small-business requirement; review the size criteria in the original notice."

    return "unknown", "The rule could not be evaluated automatically; compare the original notice with the profile."


def evaluate_condition(cond: Condition, profile: Profile) -> str:
    """Return 'satisfied', 'conflict', or 'unknown'."""
    return _evaluate_with_reason(cond, profile)[0]


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
    of ELIGIBLE. An empty extraction is also CHECK: no conditions is not
    evidence that the applicant is eligible.
    """
    if override:
        check_reasons: list[str] = []
        try:
            verdict = Verdict(override)
        except ValueError:
            verdict = Verdict.CHECK
            check_reasons.append("The manual override is unrecognized; review and select a valid eligibility verdict.")
        if verdict == Verdict.CHECK and not check_reasons:
            check_reasons.append("A manual override set this result to CHECK; review the original notice before deciding eligibility.")
        return VerdictRow(
            opportunity_id=opportunity_id,
            profile_id=profile.id,
            verdict=verdict,
            conditions=list(conditions),
            override=override,
            check_reasons=check_reasons,
        )

    disqualifying: list[str] = []
    check_quotes: list[str] = []
    check_reasons = []
    if unverified:
        check_reasons.append("Source quote verification failed for one or more extracted conditions (missing or non-verbatim quote); review the original notice.")
    elif not conditions:
        check_reasons.append("No eligibility conditions were extracted; review the original notice before deciding eligibility.")
    any_unknown = not conditions or bool(unverified)

    for cond in conditions:
        result, reason = _evaluate_with_reason(cond, profile)
        if result == "conflict":
            if cond.quote and cond.quote not in disqualifying:
                disqualifying.append(cond.quote)
        elif result == "unknown":
            any_unknown = True
            if reason and reason not in check_reasons:
                check_reasons.append(reason)
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
        check_reasons=check_reasons,
        conditions=list(conditions),
    )
