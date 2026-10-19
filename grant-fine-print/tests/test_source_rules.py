"""Synthetic, source-sentence tests; no fixtures, data files or model calls."""

from copy import deepcopy

import pytest

from src.models import Condition, ConditionType, Polarity, Profile
from src.source_rules import interpret_source_rule


def _condition(quote, value="nonprofit", *, kind=ConditionType.ORG_TYPE,
               polarity=Polarity.REQUIRED):
    return Condition(type=kind, polarity=polarity, value=value, quote=quote)


def _profile(org_type="nonprofit", us_based=True, **kwargs):
    return Profile(id="synthetic", name="Synthetic", org_type=org_type,
                   us_based=us_based, **kwargs)


@pytest.mark.parametrize("subject,value", [
    ("Foreign organizations", "foreign"),
    ("Non-U.S. entities", "non-U.S."),
    ("Non–U.S.-based organizations", "non-US-based"),
    ("Non-domestic organizations", "non-domestic"),
    ("Non-domestic (non-U.S.) Entities (Foreign Organizations)", "foreign organizations"),
    ("Non-domestic (non-U.S.) Entities (Foreign Organization)", "foreign organizations"),
    ("Organizations based outside the United States", "outside the US"),
    ("Organizations located outside of the U.S.", "outside of the US"),
])
@pytest.mark.parametrize("kind", [ConditionType.LOCATION, ConditionType.ORG_TYPE,
                                 ConditionType.CITIZENSHIP_OR_RESIDENCY])
@pytest.mark.parametrize("us_based,expected", [(True, "satisfied"), (False, "conflict")])
def test_foreign_entity_exclusions_use_entity_geography(subject, value, kind,
                                                       us_based, expected):
    condition = _condition(f"{subject} are not eligible to apply.", value,
                           kind=kind, polarity=Polarity.EXCLUDED)
    assert interpret_source_rule(condition, _profile(us_based=us_based)) == expected


@pytest.mark.parametrize("quote,value,domestic", [
    ("Only U.S.-based organizations may apply.", "U.S.-based", True),
    ("Eligible applicants are domestic organizations.", "domestic", True),
    ("Only organizations based in the U.S. may apply.", "US", True),
    ("Only organizations located in the United States may apply.", "USA", True),
    ("Applicant organizations must be based in the U.S.", "US", True),
    ("Entities must be located in the United States.", "domestic", True),
    ("Organizations must be based outside the United States.", "foreign", False),
    ("Applicant entities must be located outside of the U.S.", "non-U.S.", False),
    ("Only foreign organizations may apply.", "foreign organizations", False),
])
@pytest.mark.parametrize("us_based", [True, False])
def test_required_geography(quote, value, domestic, us_based):
    condition = _condition(quote, value, kind=ConditionType.LOCATION)
    expected = "satisfied" if us_based == domestic else "conflict"
    assert interpret_source_rule(condition, _profile(us_based=us_based)) == expected


@pytest.mark.parametrize("quote,value", [
    ("For-profit organizations are not eligible to apply.", "for-profit organization"),
    ("For-profit entities are ineligible for funding.", "for_profit"),
    ("Businesses may not apply.", "business"),
    ("For-profits cannot apply.", "for-profit"),
    ("Companies are excluded.", "company"),
    ("A for-profit organization is not eligible.", "for-profit"),
])
@pytest.mark.parametrize("org_type,expected", [
    ("for_profit", "conflict"), ("small_business", "conflict"),
    ("nonprofit", "satisfied"), ("university", "unknown"),
])
def test_explicit_for_profit_exclusions(quote, value, org_type, expected):
    condition = _condition(quote, value, polarity=Polarity.EXCLUDED)
    assert interpret_source_rule(condition, _profile(org_type)) == expected


@pytest.mark.parametrize("quote,value,org_type", [
    ("Only nonprofits may apply.", "nonprofit", "nonprofit"),
    ("Only non-profit organizations may apply.", "non-profit", "nonprofit"),
    ("Applicants must be a not-for-profit organization.", "not-for-profit", "nonprofit"),
    ("Eligibility is limited to businesses.", "business", "for_profit"),
    ("Eligible applicants are universities.", "university", "university"),
    ("Only institutions of higher education may apply.", "institution of higher education",
     "university"),
    ("Only IHEs may apply.", "IHE", "university"),
])
def test_generic_single_category_requirements(quote, value, org_type):
    assert interpret_source_rule(_condition(quote, value), _profile(org_type)) == "satisfied"


@pytest.mark.parametrize("quote", [
    "Only nonprofits or universities may apply.",
    "Eligible applicants are nonprofit organizations and universities.",
    "Eligible applicants are universities or nonprofits.",
    "Eligibility is limited to nonprofits and institutions of higher education.",
    "Applicants must be nonprofits or universities.",
])
@pytest.mark.parametrize("value", ["nonprofit", "university", "nonprofits or universities"])
@pytest.mark.parametrize("org_type,expected", [
    ("nonprofit", "satisfied"), ("university", "satisfied"),
    ("for_profit", "conflict"), ("small_business", "conflict"),
])
def test_complete_applicant_list_is_one_union_not_split_requirements(quote, value,
                                                                    org_type, expected):
    assert interpret_source_rule(_condition(quote, value), _profile(org_type)) == expected


@pytest.mark.parametrize("quote", [
    "Only nonprofits, businesses, or universities may apply.",
    "Eligible applicants are nonprofits, businesses and universities.",
    "Eligible applicants are nonprofits, businesses, and universities.",
    "Only nonprofits or businesses or universities may apply.",
])
@pytest.mark.parametrize("org_type", ["nonprofit", "for_profit", "university"])
def test_all_supported_three_branch_lists(quote, org_type):
    assert interpret_source_rule(_condition(quote), _profile(org_type)) == "satisfied"


@pytest.mark.parametrize("quote", [
    "Applicants include nonprofits or universities.",
    "Eligible applicants include nonprofit organizations and universities.",
    "Nonprofits or universities may apply.",
    "Nonprofits and universities are eligible to apply.",
    "Nonprofits are eligible for funding.",
    "Nonprofits may apply.",
])
def test_nonexhaustive_permissions_never_exclude_an_unlisted_type(quote):
    condition = _condition(quote)
    assert interpret_source_rule(condition, _profile("nonprofit")) == "satisfied"
    assert interpret_source_rule(condition, _profile("for_profit")) == "unknown"


@pytest.mark.parametrize("quote", [
    "Nonprofits or universities may not apply.",
    "Nonprofit organizations and universities are not eligible to apply.",
    "Nonprofits and universities are excluded.",
])
@pytest.mark.parametrize("org_type,expected", [
    ("nonprofit", "conflict"), ("university", "conflict"), ("for_profit", "satisfied"),
])
def test_excluded_list_is_a_union(quote, org_type, expected):
    condition = _condition(quote, polarity=Polarity.EXCLUDED)
    assert interpret_source_rule(condition, _profile(org_type)) == expected


@pytest.mark.parametrize("quote", [
    "Only domestic organizations or foreign organizations may apply.",
    "Eligible applicants are domestic organizations and foreign organizations.",
])
@pytest.mark.parametrize("us_based", [True, False])
def test_supported_geographic_list_uses_whole_union(quote, us_based):
    condition = _condition(quote, "foreign", kind=ConditionType.LOCATION)
    assert interpret_source_rule(condition, _profile(us_based=us_based)) == "satisfied"


@pytest.mark.parametrize("quote,value,polarity", [
    ("Only nonprofits may apply.", "nonprofit", Polarity.EXCLUDED),
    ("For-profit organizations may not apply.", "for-profit", Polarity.REQUIRED),
    ("Foreign organizations may not apply.", "foreign", Polarity.REQUIRED),
    ("Only foreign organizations may apply.", "foreign", Polarity.EXCLUDED),
    ("Applicants include nonprofits or universities.", "nonprofit", Polarity.EXCLUDED),
    ("Only nonprofits or universities may apply.", "university", Polarity.EXCLUDED),
])
@pytest.mark.parametrize("org_type,us_based", [("nonprofit", True), ("for_profit", False)])
def test_polarity_mismatches_abstain_in_both_directions(quote, value, polarity,
                                                      org_type, us_based):
    condition = _condition(quote, value, polarity=polarity)
    assert interpret_source_rule(condition, _profile(org_type, us_based)) == "unknown"


@pytest.mark.parametrize("value", [
    "for-profit", "government", "not a nonprofit", "nonprofit unless approved",
    "nonprofit or government", "nonprofit and for-profit", "private university",
    "nonprofit university", "", " \n ", None, 17,
])
def test_model_value_cannot_inject_a_branch_or_qualifier(value):
    condition = _condition("Only nonprofits or universities may apply.", value)
    assert interpret_source_rule(condition, _profile("for_profit")) == "unknown"


@pytest.mark.parametrize("value", ["US", "domestic", "US-based organizations", "nonprofit"])
@pytest.mark.parametrize("us_based", [True, False])
def test_conflicting_geography_value_cannot_reverse_source_exclusion(value, us_based):
    condition = _condition("Foreign organizations are not eligible to apply.", value,
                           kind=ConditionType.LOCATION, polarity=Polarity.EXCLUDED)
    assert interpret_source_rule(condition, _profile(us_based=us_based)) == "unknown"


@pytest.mark.parametrize("kind", [
    ConditionType.CITIZENSHIP_OR_RESIDENCY, ConditionType.LOCATION,
    ConditionType.SIZE, ConditionType.OTHER, ConditionType.PARTNERSHIP_REQUIRED,
    ConditionType.PRIOR_AWARD_OR_STATUS, ConditionType.COST_SHARE,
])
def test_organization_rules_do_not_correct_unrelated_model_types(kind):
    condition = _condition("Businesses may not apply.", "business", kind=kind,
                           polarity=Polarity.EXCLUDED)
    assert interpret_source_rule(condition, _profile("for_profit")) == "unknown"


@pytest.mark.parametrize("kind", [ConditionType.SIZE, ConditionType.OTHER,
                                 ConditionType.PARTNERSHIP_REQUIRED])
def test_geography_only_has_documented_type_correction(kind):
    condition = _condition("Foreign organizations may not apply.", "foreign", kind=kind,
                           polarity=Polarity.EXCLUDED)
    assert interpret_source_rule(condition, _profile(us_based=False)) == "unknown"


@pytest.mark.parametrize("polarity", [None, "not required", "", 42])
def test_invalid_polarity_is_not_truthy_exclusion(polarity):
    condition = _condition("Only nonprofits may apply.", polarity=polarity)
    assert interpret_source_rule(condition, _profile("for_profit")) == "unknown"


@pytest.mark.parametrize("quote", [
    # Every branch must be supported, even when a supported branch matches.
    "Only nonprofits or tribal governments may apply.",
    "Eligible applicants are nonprofits, universities, and individuals.",
    "Applicants include nonprofits and local governments.",
    "Nonprofits or other organizations may apply.",
    "Only nonprofits or universities or other entities may apply.",
    # A subtype is not an independent OR, nor established by a coarse profile.
    "Only nonprofit universities may apply.",
    "Nonprofit universities may apply.",
    "Only nonprofit institutions of higher education may apply.",
    "Only private universities may apply.",
    "Public universities are not eligible to apply.",
    "Only private nonprofit organizations may apply.",
    "Only 501(c)(3) nonprofit organizations may apply.",
    "Only small businesses may apply.",
    "Only for-profit research organizations may apply.",
    "Only nonprofits or private universities may apply.",
    "Eligible applicants are nonprofits and accredited universities.",
    # No conditional, prior-status, partnership or residual clauses.
    "Only nonprofits may apply unless a waiver is granted.",
    "Only nonprofits may apply except universities.",
    "Only nonprofits may apply provided they have prior awards.",
    "Only nonprofits with prior awards may apply.",
    "Only nonprofits in partnership with universities may apply.",
    "Eligible applicants are nonprofits and universities with prior awards.",
    "Only nonprofits or universities in partnership may apply.",
    "Foreign organizations may not apply except with a domestic partner.",
    "Foreign organizations may not apply unless invited.",
    "Foreign organizations with U.S. offices may not apply.",
    "Foreign organizations may not apply for this component.",
    "Only nonprofits may apply for research awards.",
    "Only nonprofits may apply if based in the U.S.",
    "Only nonprofits that are not universities may apply.",
    # Extra negation, contradictions and mixed sentences cannot be discarded.
    "Not only nonprofits may apply.",
    "Only non-nonprofits may apply.",
    "Only not nonprofits may apply.",
    "Nonprofits are not ineligible to apply.",
    "Foreign organizations are not excluded.",
    "Nonprofits may not not apply.",
    "It is not true that foreign organizations may not apply.",
    "Only nonprofits may apply and nonprofits may not apply.",
    "Only nonprofits may apply. Universities may also apply.",
    "Foreign organizations may not apply. Foreign organizations may apply.",
    "Only nonprofits may apply; universities may apply.",
    "Only nonprofits may apply: universities may also apply.",
    "\"Only nonprofits may apply.\" is an example.",
    # No project or individual geography interpreted as entity geography.
    "Projects outside the U.S. are not eligible to apply.",
    "Research in foreign countries is not eligible.",
    "Foreign citizens are not eligible to apply.",
    "Foreign partnerships are not eligible to apply.",
    "Only U.S. citizens may apply.",
    "Applicants must conduct projects in the United States.",
    "Applicants must be U.S.-based.",
    # Unsupported/mixed categories and ambiguous logical grouping.
    "Only governments may apply.",
    "Only individuals may apply.",
    "Only nonprofits and universities may apply.",
    "Applicants must be nonprofits and universities.",
    "Eligible applicants are nonprofits and universities or businesses.",
    "Only nonprofits or foreign organizations may apply.",
    "Eligible applicants are nonprofits, universities.",
    "Only nonprofits or may apply.",
    "Only nonprofits,, or universities may apply.",
])
@pytest.mark.parametrize("org_type", ["nonprofit", "university", "for_profit"])
def test_unsupported_whole_sentences_are_not_salvaged(quote, org_type):
    condition = _condition(quote)
    assert interpret_source_rule(condition, _profile(org_type, us_based=False)) is None


@pytest.mark.parametrize("quote", [
    "Nonprofits", "foreign organizations", "not eligible to apply.",
    "Only nonprofits may apply", "Only nonprofits may", "Only nonprofits or universities.",
    "Only nonprofits may apply...", "Only nonprofits may apply..",
    "Only nonprofits may apply!", "", " \n ", None, 37,
])
def test_missing_truncated_or_non_sentence_quote_cannot_use_model_value(quote):
    assert interpret_source_rule(_condition(quote), _profile()) is None


@pytest.mark.parametrize("quote", [
    "Foreign components are not eligible to apply.",
    "Non-domestic (non-U.S.) components of U.S. organizations are not eligible to apply.",
    "Foreign components of domestic organizations may apply.",
    "Applicants must be U.S. citizens.",
    "Individuals must be U.S. residents.",
    "U.S. citizens may not apply.",
    "Applicants must partner with domestic organizations.",
    "Applicants must apply in partnership with U.S.-based organizations.",
])
@pytest.mark.parametrize("us_based", [True, False])
def test_unobservable_scopes_never_reuse_entity_location(quote, us_based):
    condition = _condition(quote, "foreign", kind=ConditionType.CITIZENSHIP_OR_RESIDENCY,
                           polarity=Polarity.EXCLUDED)
    assert interpret_source_rule(condition, _profile(us_based=us_based)) == "unknown"


@pytest.mark.parametrize("us_based", [None, "false", "true", "US", 0, 1])
def test_geography_requires_a_real_boolean(us_based):
    condition = _condition("Foreign organizations may not apply.", "foreign",
                           kind=ConditionType.LOCATION, polarity=Polarity.EXCLUDED)
    assert interpret_source_rule(condition, _profile(us_based=us_based)) == "unknown"


@pytest.mark.parametrize("org_type", ["individual", "person", "", "unknown", "other"])
def test_person_profile_does_not_establish_organizational_location(org_type):
    condition = _condition("Foreign organizations may not apply.", "foreign",
                           kind=ConditionType.LOCATION, polarity=Polarity.EXCLUDED)
    assert interpret_source_rule(condition, _profile(org_type, False)) == "unknown"


@pytest.mark.parametrize("org_type", ["", "other", "unknown", "government", "individual",
                                      "nonprofit university", "private university"])
def test_unknown_or_unsupported_profile_type_abstains(org_type):
    condition = _condition("Only nonprofits or universities may apply.")
    assert interpret_source_rule(condition, _profile(org_type)) == "unknown"


@pytest.mark.parametrize("quote,value", [
    ("Only nonprofits may apply.", "nonprofit"),
    ("Only businesses may apply.", "business"),
    ("Nonprofits may not apply.", "nonprofit"),
    ("Businesses may not apply.", "business"),
])
def test_university_profile_does_not_reveal_profit_status(quote, value):
    polarity = Polarity.EXCLUDED if "may not" in quote else Polarity.REQUIRED
    condition = _condition(quote, value, polarity=polarity)
    assert interpret_source_rule(condition, _profile("university")) == "unknown"


def test_full_quote_drives_union_despite_model_selecting_only_one_branch():
    quote = "Only nonprofits or universities may apply."
    condition = _condition(quote, "nonprofit")
    assert interpret_source_rule(condition, _profile("university")) == "satisfied"
    # The same extracted branch cannot rescue an unsupported second branch.
    condition.quote = "Only nonprofits or private universities may apply."
    assert interpret_source_rule(condition, _profile("nonprofit")) is None


def test_case_whitespace_and_hyphens_do_not_change_semantics_or_inputs():
    condition = _condition(" \n ONLY  Non–Profit organizations\n or UNIVERSITIES may apply.\t",
                           "non-profit")
    profile = _profile("university", notes="A synthetic note; not eligibility evidence.")
    originals = deepcopy((condition, profile))
    assert [interpret_source_rule(condition, profile) for _ in range(3)] == ["satisfied"] * 3
    assert (condition, profile) == originals


def test_profile_notes_and_names_are_not_legal_status_evidence():
    condition = _condition("Businesses may not apply.", "business",
                           polarity=Polarity.EXCLUDED)
    profile = _profile("university", notes="for-profit; private; located abroad")
    profile.name = "For-profit University"
    assert interpret_source_rule(condition, profile) == "unknown"


def test_absent_condition_is_not_supplemented_from_profile_or_value():
    condition = _condition("", "Foreign organizations are not eligible to apply.",
                           kind=ConditionType.CITIZENSHIP_OR_RESIDENCY,
                           polarity=Polarity.EXCLUDED)
    assert interpret_source_rule(condition, _profile(us_based=False)) is None
