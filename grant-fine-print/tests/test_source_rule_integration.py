"""Narrow matching flow tested on invented notices, not benchmark labels."""

import pytest

from src.match import match
from src.models import Condition, ConditionType, Polarity, Profile, Verdict
from src.verify import verify_conditions


def screen(quote, value, kind, polarity, profile, source=None):
    raw = [Condition(kind, polarity, value, quote)]
    verified = verify_conditions(raw, quote if source is None else source)
    return match(verified.verified, profile, "synthetic",
                 unverified=[condition for condition, _ in verified.dropped])


def test_organizational_geography_is_not_personal_citizenship():
    profile = Profile("p", "Foreign nonprofit", org_type="nonprofit", us_based=False)
    quote = "Foreign organizations are not eligible to apply."
    row = screen(quote, "foreign organizations", ConditionType.CITIZENSHIP_OR_RESIDENCY,
                 Polarity.EXCLUDED, profile)
    assert row.verdict == Verdict.NOT_ELIGIBLE
    assert row.disqualifying_quotes == [quote]


@pytest.mark.parametrize("kind", [ConditionType.LOCATION, ConditionType.CITIZENSHIP_OR_RESIDENCY])
@pytest.mark.parametrize("quote", [
    "Foreign components, as defined in agency policy, are not allowed.",
    "Non-domestic components of U.S. organizations are not eligible to apply.",
    "Applicants must be U.S. citizens.",
    "Projects outside the United States are not eligible.",
])
def test_distinct_geographic_facts_are_not_substituted(kind, quote):
    profile = Profile("p", "Foreign nonprofit", org_type="nonprofit", us_based=False)
    row = screen(quote, "foreign organizations", kind, Polarity.EXCLUDED, profile)
    assert row.verdict == Verdict.CHECK
    assert row.disqualifying_quotes == []
    assert row.check_reasons


@pytest.mark.parametrize("org_type,verdict", [
    ("university", Verdict.ELIGIBLE), ("nonprofit", Verdict.ELIGIBLE),
    ("for_profit", Verdict.NOT_ELIGIBLE),
])
def test_source_list_is_a_union_even_when_model_splits_it(org_type, verdict):
    quote = "Only nonprofits or universities may apply."
    conditions = [Condition(ConditionType.ORG_TYPE, Polarity.REQUIRED, value, quote)
                  for value in ("nonprofit", "university")]
    verified = verify_conditions(conditions, quote)
    row = match(verified.verified, Profile("p", "Example", org_type=org_type), "synthetic")
    assert row.verdict == verdict
    assert row.disqualifying_quotes == ([quote] if verdict == Verdict.NOT_ELIGIBLE else [])


@pytest.mark.parametrize("quote", [
    "Applicants include nonprofits or universities.",
    "Nonprofits or universities may apply.",
    "Only nonprofits or private universities may apply.",
    "Only nonprofits or universities with prior awards may apply.",
])
def test_unlisted_or_unobserved_applicant_is_not_automatically_rejected(quote):
    row = screen(quote, "nonprofit", ConditionType.ORG_TYPE, Polarity.REQUIRED,
                 Profile("p", "Example", org_type="for_profit"))
    assert row.verdict == Verdict.CHECK


def test_polarity_disagrees_with_source_requires_review():
    row = screen("Businesses may apply.", "business", ConditionType.ORG_TYPE,
                 Polarity.EXCLUDED, Profile("p", "Example", org_type="for_profit"))
    assert row.verdict == Verdict.CHECK


def test_unverified_quote_cannot_use_the_source_interpreter():
    row = screen("Foreign organizations may not apply.", "foreign", ConditionType.LOCATION,
                 Polarity.EXCLUDED, Profile("p", "Example", org_type="nonprofit", us_based=False),
                 source="Organizations may apply.")
    assert row.verdict == Verdict.CHECK
    assert row.disqualifying_quotes == []


@pytest.mark.parametrize("quote", [
    "Institutions of higher education: accredited degree-granting institutions.",
    "Universities that have a research office may apply.",
    "Universities are eligible for this funding opportunity.",
])
def test_one_positive_applicant_route_is_not_an_exclusive_restriction(quote):
    source = quote + " Nonprofit research organizations may also apply."
    row = screen(quote, "institution of higher education", ConditionType.ORG_TYPE,
                 Polarity.REQUIRED, Profile("p", "Nonprofit", org_type="nonprofit"),
                 source=source)
    assert row.verdict == Verdict.CHECK
    assert row.disqualifying_quotes == []


@pytest.mark.parametrize("quote,kind,value", [
    ("For-profit organizations are not eligible to apply unless they hold a waiver.",
     ConditionType.ORG_TYPE, "for-profit organizations"),
    ("Institutions of higher education must have a campus in the United States.",
     ConditionType.LOCATION, "U.S.-based"),
    ("The designated institutes are located in the United States.",
     ConditionType.LOCATION, "U.S.-based"),
])
def test_unsupported_whole_rule_cannot_fall_back_to_keyword_rejection(quote, kind, value):
    polarity = Polarity.EXCLUDED if kind == ConditionType.ORG_TYPE else Polarity.REQUIRED
    row = screen(quote, value, kind, polarity,
                 Profile("p", "Foreign business", org_type="for_profit", us_based=False))
    assert row.verdict == Verdict.CHECK
    assert row.disqualifying_quotes == []
