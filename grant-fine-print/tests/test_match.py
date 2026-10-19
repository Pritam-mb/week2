"""Synthetic matcher regressions; no benchmark data or model calls."""

import pytest

from src.match import evaluate_condition, match
from src.models import Condition, ConditionType, Polarity, Profile, Verdict
from src.verify import verify_conditions


def _profile(**kwargs):
    return Profile(id="synthetic-profile", name="Synthetic", **kwargs)


def _condition(value, *, kind=ConditionType.ORG_TYPE,
               polarity=Polarity.REQUIRED, quote=None):
    return Condition(kind, polarity, value, quote if quote is not None else value)


@pytest.mark.parametrize("org_type", ["nonprofit", "university", "government"])
@pytest.mark.parametrize("quote", [
    "Nonprofit organizations or universities may apply.",
    "Eligible applicants include nonprofits, universities, and state governments.",
])
def test_supported_alternatives_use_union_unsupported_lists_abstain(org_type, quote):
    conditions = [
        _condition("nonprofit organization", quote=quote),
        _condition("university", quote=quote),
    ]
    verified = verify_conditions(conditions, quote).verified
    row = match(verified, _profile(org_type=org_type), "synthetic-opportunity")
    supported = " or " in quote and org_type in {"nonprofit", "university"}
    assert row.verdict == (Verdict.ELIGIBLE if supported else Verdict.CHECK)
    assert row.disqualifying_quotes == []
    assert row.check_quotes == ([] if supported else [quote])
    assert len(row.check_reasons) == (0 if supported else 1)
    assert row.conditions == conditions


@pytest.mark.parametrize("kind,value", [
    (ConditionType.ORG_TYPE, "nonprofit or university"),
    (ConditionType.LOCATION, "U.S. or foreign"),
    (ConditionType.SIZE, "small business or university"),
])
@pytest.mark.parametrize("polarity", list(Polarity))
def test_alternative_in_value_is_unknown(kind, value, polarity):
    condition = _condition(value, kind=kind, polarity=polarity,
                           quote="Applicants may meet either alternative.")
    assert evaluate_condition(condition, _profile(org_type="nonprofit")) == "unknown"


@pytest.mark.parametrize("value", [
    "non-U.S.-based", "non US organizations", "non-USA organizations",
    "outside the U.S.", "outside the United States", "outside the US",
    "outside of the United States", "foreign organizations", "non–U.S.-based",
    "outside the U.S", "non-domestic organizations",
])
@pytest.mark.parametrize("us_based", [True, False])
@pytest.mark.parametrize("polarity", list(Polarity))
def test_non_us_location_respects_polarity(value, us_based, polarity):
    condition = _condition(value, kind=ConditionType.LOCATION, polarity=polarity)
    expected = "satisfied" if (not us_based) == (polarity == Polarity.REQUIRED) else "conflict"
    if expected == "conflict":
        expected = "unknown"  # A value/phrase alone is not a complete source restriction.
    assert evaluate_condition(condition, _profile(us_based=us_based)) == expected


@pytest.mark.parametrize("value", [
    "U.S.-based", "U.S", "U.S.A.", "United States", "USA", "US", "domestic",
])
@pytest.mark.parametrize("us_based", [True, False])
@pytest.mark.parametrize("polarity", list(Polarity))
def test_us_location_respects_polarity(value, us_based, polarity):
    condition = _condition(value, kind=ConditionType.LOCATION, polarity=polarity)
    expected = "satisfied" if us_based == (polarity == Polarity.REQUIRED) else "conflict"
    if expected == "conflict":
        expected = "unknown"
    assert evaluate_condition(condition, _profile(us_based=us_based)) == expected


@pytest.mark.parametrize("value", [
    "foreign and domestic organizations", "U.S. and non-U.S. applicants",
    "business organizations", "usual residence", "specified location",
])
def test_mixed_or_unrecognized_location_is_unknown(value):
    condition = _condition(value, kind=ConditionType.LOCATION)
    assert evaluate_condition(condition, _profile()) == "unknown"


@pytest.mark.parametrize("value", [
    "capacity building organizations", "public health organizations",
    "private foundations", "public agencies", "publicity groups",
    "nonprofit university", "nonprofit and for-profit organizations",
    "federally recognized research institution",
])
@pytest.mark.parametrize("polarity", list(Polarity))
def test_organization_keyword_collisions_abstain(value, polarity):
    condition = _condition(value, polarity=polarity)
    assert evaluate_condition(condition, _profile(org_type="university")) == "unknown"


@pytest.mark.parametrize("value,org_type", [
    ("nonprofit organization", "nonprofit"),
    ("non-profit organizations", "nonprofit"),
    ("not-for-profit organization", "nonprofit"),
    ("501(c)(3) nonprofit", "nonprofit"),
    ("for-profit organization", "for_profit"),
    ("small business", "small_business"),
    ("small businesses", "small_business"),
    ("public university", "university"),
    ("private university", "university"),
    ("universities", "university"),
    ("federally recognized tribal government", "tribal"),
    ("state government", "government"),
    ("city government", "government"),
    ("individual applicant", "individual"),
])
def test_simple_organization_rules_remain_supported(value, org_type):
    profile = _profile(org_type=org_type)
    required = _condition(value)
    excluded = _condition(value, polarity=Polarity.EXCLUDED)
    assert evaluate_condition(required, profile) == "satisfied"
    assert evaluate_condition(excluded, profile) == "unknown"
    assert match([required], profile, "synthetic").verdict == Verdict.ELIGIBLE
    row = match([excluded], profile, "synthetic")
    assert row.verdict == Verdict.CHECK
    assert row.disqualifying_quotes == []


@pytest.mark.parametrize("org_type", ["", "other", "unrecognized"])
@pytest.mark.parametrize("polarity", list(Polarity))
def test_unknown_profile_organization_is_not_evidence(org_type, polarity):
    condition = _condition("nonprofit organization", polarity=polarity)
    row = match([condition], _profile(org_type=org_type), "synthetic")
    assert row.verdict == Verdict.CHECK
    assert row.check_quotes == [condition.quote]
    assert "profile's organization type" in row.check_reasons[0]


@pytest.mark.parametrize("value,quote", [
    ("", "Only nonprofits may apply."),
    ("   ", "Only nonprofits may apply."),
    (None, "Only nonprofits may apply."),
    ("nonprofit", ""),
    ("nonprofit", " \n "),
])
def test_empty_value_or_quote_cannot_establish_eligibility(value, quote):
    condition = _condition(value, quote=quote)
    row = match([condition], _profile(org_type="for_profit"), "synthetic")
    assert row.verdict == Verdict.CHECK
    assert row.disqualifying_quotes == []
    assert row.check_reasons


def test_empty_extraction_requires_check():
    row = match([], _profile(org_type="nonprofit"), "synthetic")
    assert row.verdict == Verdict.CHECK
    assert row.conditions == []
    assert row.disqualifying_quotes == []
    assert row.check_quotes == []
    assert "No eligibility conditions were extracted" in row.check_reasons[0]


@pytest.mark.parametrize("polarity", list(Polarity))
def test_unknown_location_profile_requires_check(polarity):
    condition = _condition("U.S.-based", kind=ConditionType.LOCATION, polarity=polarity)
    assert evaluate_condition(condition, _profile(us_based=None)) == "unknown"


@pytest.mark.parametrize("kind", [ConditionType.SIZE, ConditionType.ORG_TYPE])
@pytest.mark.parametrize("polarity", list(Polarity))
def test_small_business_size_polarity_and_missing_size(kind, polarity):
    condition = _condition("small business", kind=kind, polarity=polarity)
    for profile in [_profile(org_type="small_business"),
                    _profile(org_type="for_profit", size_band="small")]:
        expected = "satisfied" if polarity == Polarity.REQUIRED else "conflict"
        if expected == "conflict":
            expected = "unknown"
        assert evaluate_condition(condition, profile) == expected
    assert evaluate_condition(condition, _profile(org_type="for_profit")) == "unknown"
    assert evaluate_condition(condition, _profile(org_type="nonprofit", size_band="small")) == "unknown"
    expected = "unknown" if polarity == Polarity.REQUIRED else "satisfied"
    assert evaluate_condition(condition, _profile(org_type="for_profit", size_band="large")) == expected


def test_dropped_conflict_cannot_disqualify():
    conditions = [_condition("nonprofit", quote="A fabricated quote.")]
    result = verify_conditions(conditions, "Only nonprofits may apply.")
    row = match(result.verified, _profile(org_type="for_profit"), "synthetic",
                unverified=[condition for condition, _ in result.dropped])
    assert row.verdict == Verdict.CHECK
    assert row.disqualifying_quotes == []
    assert row.check_quotes == []
    assert "Source quote verification failed" in row.check_reasons[0]


def test_unverified_and_unsupported_conditions_still_force_check():
    condition = _condition("nonprofit")
    profile = _profile(org_type="nonprofit")
    unsupported = _condition("prior award", kind=ConditionType.PRIOR_AWARD_OR_STATUS)
    row = match([condition, unsupported], profile, "synthetic")
    assert row.verdict == Verdict.CHECK
    assert row.check_quotes == [unsupported.quote]
    assert match([condition], profile, "synthetic", unverified=[unsupported]).verdict == Verdict.CHECK


def test_independent_verified_conflict_still_wins_over_unknown():
    quote = "Nonprofits or tribal organizations may apply."
    alternative = _condition("nonprofit", quote=quote)
    conflict = _condition("U.S.-based", kind=ConditionType.LOCATION,
                          quote="Only U.S.-based organizations may apply.")
    row = match([alternative, conflict, conflict],
                _profile(org_type="nonprofit", us_based=False), "synthetic")
    assert row.verdict == Verdict.NOT_ELIGIBLE
    assert row.disqualifying_quotes == [conflict.quote]
    assert row.check_quotes == [quote]
    assert "OR alternatives" in row.check_reasons[0]


@pytest.mark.parametrize("override,verdict", [
    ("ELIGIBLE", Verdict.ELIGIBLE), ("NOT_ELIGIBLE", Verdict.NOT_ELIGIBLE),
    ("CHECK", Verdict.CHECK), ("invalid", Verdict.CHECK),
])
def test_override_compatibility(override, verdict):
    row = match([], _profile(), "synthetic", override=override)
    assert row.verdict == verdict
    assert row.override == override
    if verdict == Verdict.CHECK:
        assert "manual override" in row.check_reasons[0]
    else:
        assert row.check_reasons == []
