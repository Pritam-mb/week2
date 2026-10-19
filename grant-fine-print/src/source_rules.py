"""Small, closed grammar for ONE already source-verified model condition.

Contract
--------
``interpret_source_rule`` returns ``None`` when the *whole quoted sentence* is
outside the grammar. It returns ``unknown`` for a recognized sentence whose
metadata or profile facts do not justify a verdict. ``satisfied`` and
``conflict`` concern this one restriction, never overall grant eligibility.

Supported sentence frames (case/whitespace and hyphen variants are normalized):

* Only <subjects> may apply. / Applicants must be <subjects>.
* Eligible applicants are <subjects>. / Eligibility is limited to <subjects>.
* [Eligible] applicants include <subjects>.
* <subjects> may apply / are eligible [to apply / for funding].
* <subjects> may not apply / cannot apply / are not eligible [to apply /
  for funding] / are ineligible [to apply / for funding] / are excluded.
* [Applicant] organizations/entities must be based/located in/outside the U.S.

A final period is required. Subjects are exact generic nonprofit, business /
for-profit, university / institution-of-higher-education, or domestic / foreign
organization phrases. Homogeneous OR lists are supported; AND enumeration is
also supported in applicant-list and exclusion frames, but not in "Only" or
"must be" frames. Every branch must parse, with no leftover text. Geographic
and organization-type categories cannot be mixed in one list. ``include`` and
plain permission frames are nonexhaustive: an unlisted type is ``unknown``.

Source polarity determines meaning. Model polarity must agree; model value
must name a supported branch or subset of the source list (split extractions
are allowed). Model type must agree as well. The sole type correction permits
citizenship_or_residency for *explicit organizational* geography, never people,
components, projects or partnerships. Explicit simple component/citizen/
partnership frames below are recognized only to return ``unknown``.

Qualifying subtypes (including private/public or nonprofit universities),
exceptions, conditional clauses, residual qualifiers, unsupported branches,
contradictions, additional negation and multiple sentences are not grammar.
University profiles do not establish their legal profit status. Unknown profile
types and nonboolean geography abstain. No source lookup, extraction, IO,
environment access, model calls, matcher fallback or supplementation occurs.
The caller is responsible for verifying the quote against the source first.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .models import Condition, ConditionType, Polarity, Profile

__all__ = ["interpret_source_rule"]


def _text(value: object) -> str:
    if not isinstance(value, str):
        return ""
    text = re.sub(r"\s+", " ", value).strip().lower()
    text = re.sub(r"[\u2010-\u2015\u2212]", "-", text)
    # Abbreviations are normalized without treating their periods as sentence
    # boundaries. Full matching below still rejects extra sentences/clauses.
    return re.sub(
        r"(?<!\w)(?:u\.s(?:\.a)?\.?|usa|united states(?: of america)?)(?!\w)",
        "us", text,
    )


_ENTITY = r"(?:organizations?|entities|entity)"
_NONPROFIT = r"(?:non-?profit|not-for-profit)(?:s| " + _ENTITY + r")?"
_BUSINESS = (
    r"(?:for-profit(?:s| (?:" + _ENTITY + r"|business(?:es)?))?"
    r"|business(?:es)?|compan(?:y|ies))"
)
_UNIVERSITY = r"(?:universit(?:y|ies)|institutions? of higher education|ihes?)"
_DOMESTIC = (
    r"(?:(?:domestic|us(?:-based)?) " + _ENTITY
    + r"|" + _ENTITY + r" (?:based|located) in (?:the )?us)"
)
_FOREIGN = (
    r"(?:(?:foreign|non-us(?:-based)?|non-domestic(?: \(non-us\))?) "
    + _ENTITY + r"(?: \(foreign organizations?\))?"
    r"|" + _ENTITY + r" (?:based|located) outside (?:of )?(?:the )?us)"
)
_ATOMS = tuple(
    (name, re.compile(pattern))
    for name, pattern in (
        ("nonprofit", _NONPROFIT), ("business", _BUSINESS),
        ("university", _UNIVERSITY), ("domestic", _DOMESTIC),
        ("foreign", _FOREIGN),
    )
)
_GEOGRAPHY = frozenset({"domestic", "foreign"})


def _atom(text: str) -> str | None:
    text = re.sub(r"^(?:a|an) ", "", text)
    for name, pattern in _ATOMS:
        if pattern.fullmatch(text):
            return name
    return None


def _subjects(text: str, *, allow_and: bool) -> frozenset[str] | None:
    """Parse an entire enumeration, never collect keyword hits from prose."""
    conjunctions = set(re.findall(r"\b(?:and|or)\b", text))
    if len(conjunctions) > 1 or ("and" in conjunctions and not allow_and):
        return None
    if "," in text:
        # Comma lists must end in an explicit coordinator and a final branch.
        if not re.search(r"\b(?:and|or) [^,]+$", text):
            return None
    parts = re.split(r", (?:and |or )?| (?:and|or) ", text)
    categories = [_atom(part) for part in parts]
    if not categories or any(category is None for category in categories):
        return None
    result = frozenset(category for category in categories if category is not None)
    if result & _GEOGRAPHY and not result <= _GEOGRAPHY:
        return None
    return result


@dataclass(frozen=True)
class _Rule:
    categories: frozenset[str]
    polarity: Polarity
    exhaustive: bool


# Frame captures consume the whole sentence body. No scanning for a tempting
# phrase inside a larger restriction, qualifier or negated statement.
_FRAMES = tuple(
    (re.compile(pattern), polarity, exhaustive, allow_and)
    for pattern, polarity, exhaustive, allow_and in (
        (r"only (.+) may apply", Polarity.REQUIRED, True, False),
        (r"applicants must be (.+)", Polarity.REQUIRED, True, False),
        (r"eligible applicants are (.+)", Polarity.REQUIRED, True, True),
        (r"eligibility is limited to (.+)", Polarity.REQUIRED, True, True),
        (r"(?:eligible )?applicants include (.+)", Polarity.REQUIRED, False, True),
        (r"(.+) may apply", Polarity.REQUIRED, False, False),
        (r"(.+) (?:are|is) eligible(?: to apply| for funding)?",
         Polarity.REQUIRED, False, True),
        (r"(.+) (?:may not|cannot) apply", Polarity.EXCLUDED, True, True),
        (r"(.+) (?:are|is) (?:not eligible|ineligible)(?: to apply| for funding)?",
         Polarity.EXCLUDED, True, True),
        (r"(.+) (?:are|is) excluded", Polarity.EXCLUDED, True, True),
    )
)
_BASED = re.compile(
    r"(?:applicant )?" + _ENTITY
    + r" must be (?:based|located) (in|outside(?: of)?) (?:the )?us"
)

# These precisely delimited subjects/frames lack corresponding profile facts.
# They are never evaluated as entity geography, irrespective of model fields.
_UNOBSERVABLE = (
    re.compile(
        r"(?:foreign|non-us|non-domestic(?: \(non-us\))?) components"
        r"(?: of (?:us|domestic) organizations)? "
        r"(?:are (?:not eligible|eligible)(?: to apply)?|may not apply|may apply)"
    ),
    re.compile(r"(?:applicants|individuals) must be (?:us citizens|us residents)"),
    re.compile(r"(?:us citizens|us residents) (?:may apply|may not apply)"),
    re.compile(r"applicants must (?:partner with|apply in partnership with) " + _DOMESTIC),
)


def _parse(body: str) -> _Rule | None:
    based = _BASED.fullmatch(body)
    if based:
        category = "domestic" if based[1] == "in" else "foreign"
        return _Rule(frozenset({category}), Polarity.REQUIRED, True)
    for frame, polarity, exhaustive, allow_and in _FRAMES:
        match = frame.fullmatch(body)
        if match:
            categories = _subjects(match[1], allow_and=allow_and)
            if categories:
                return _Rule(categories, polarity, exhaustive)
    return None


def _model_categories(value: object) -> frozenset[str] | None:
    text = _text(value)
    # Bare geography is allowed as model shorthand, never as source grammar.
    aliases = {
        "us": "domestic", "us-based": "domestic", "domestic": "domestic",
        "foreign": "foreign", "non-us": "foreign", "non-us-based": "foreign",
        "non-domestic": "foreign", "outside the us": "foreign",
        "outside of the us": "foreign", "outside us": "foreign",
        "for_profit": "business",
    }
    if text in aliases:
        return frozenset({aliases[text]})
    return _subjects(text, allow_and=True)


def _membership(category: str, profile: Profile) -> bool | None:
    org_type = _text(profile.org_type).replace("_", " ")
    if category in _GEOGRAPHY:
        if org_type not in {
            "nonprofit", "non-profit", "nonprofit organization", "for profit",
            "for-profit", "business", "small business", "university", "ihe",
            "institution of higher education", "government", "tribal",
        }:
            return None
        if type(profile.us_based) is not bool:
            return None
        return profile.us_based == (category == "domestic")

    # This is the coarse profile taxonomy, not keyword-based legal inference.
    profile_category = {
        "nonprofit": "nonprofit", "non-profit": "nonprofit",
        "nonprofit organization": "nonprofit",
        "for profit": "business", "for-profit": "business",
        "business": "business", "small business": "business",
        "university": "university", "ihe": "university",
        "institution of higher education": "university",
    }.get(org_type)
    if profile_category is None:
        return None
    if profile_category == "university" and category in {"nonprofit", "business"}:
        # A generic university profile supplies neither legal profit status.
        return None
    return profile_category == category


def interpret_source_rule(condition: Condition, profile: Profile) -> str | None:
    """Interpret one quoted rule; see the module contract for the closed grammar.

    This function does not verify provenance: it requires an already verified
    Condition, and cannot discover an omitted condition from other source text.
    Inputs are read only, and no caller/model fields can expand source grammar.
    """
    if not isinstance(condition.quote, str):
        return None
    # Strip the required sentence terminator BEFORE abbreviation normalization.
    # In particular, "U.S." at sentence end has just one final period.
    quote = condition.quote.strip()
    if not quote.endswith("."):
        return None
    body = _text(quote[:-1])
    if any(pattern.fullmatch(body) for pattern in _UNOBSERVABLE):
        return "unknown"
    rule = _parse(body)
    if rule is None:
        return None

    geography = rule.categories <= _GEOGRAPHY
    allowed_types = (
        {ConditionType.LOCATION, ConditionType.ORG_TYPE,
         ConditionType.CITIZENSHIP_OR_RESIDENCY}
        if geography else {ConditionType.ORG_TYPE}
    )
    if condition.type not in allowed_types or condition.polarity != rule.polarity:
        return "unknown"
    proposed = _model_categories(condition.value)
    if not proposed or not proposed <= rule.categories:
        return "unknown"

    memberships = [_membership(category, profile) for category in rule.categories]
    if True in memberships:
        return "satisfied" if rule.polarity == Polarity.REQUIRED else "conflict"
    if None in memberships or not rule.exhaustive:
        return "unknown"
    return "conflict" if rule.polarity == Polarity.REQUIRED else "satisfied"
