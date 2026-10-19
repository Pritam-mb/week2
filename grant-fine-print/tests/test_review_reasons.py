"""User-visible review explanations using only synthetic conditions and profiles."""

import html
import json

import pytest

from src import cards
from src.match import match
from src.models import Condition, ConditionType, Polarity, Profile, Verdict, VerdictRow
from src.verify import verify_conditions


def _condition(value="nonprofit", kind=ConditionType.ORG_TYPE, quote=None):
    return Condition(kind, Polarity.REQUIRED, value, value if quote is None else quote)


def _profile(**kwargs):
    return Profile(id="synthetic-profile", name="Synthetic", **kwargs)


@pytest.mark.parametrize("kind,label", [
    (ConditionType.CITIZENSHIP_OR_RESIDENCY, "citizenship or residency"),
    (ConditionType.PRIOR_AWARD_OR_STATUS, "prior award or status"),
    (ConditionType.PARTNERSHIP_REQUIRED, "partnership"),
    (ConditionType.COST_SHARE, "cost sharing"),
    (ConditionType.OTHER, "other eligibility"),
    ("future_condition_type", "condition type is unrecognized"),
])
def test_unsupported_condition_explains_what_needs_review(kind, label):
    condition = _condition("Applicants must meet the stated requirement.", kind)
    row = match([condition], _profile(org_type="nonprofit"), "synthetic")
    assert row.verdict == Verdict.CHECK
    assert label in row.check_reasons[0]
    assert row.check_quotes == [condition.quote]
    assert row.disqualifying_quotes == []


@pytest.mark.parametrize("condition,profile,explanation", [
    (_condition("nonprofit or university"), _profile(), "OR alternatives"),
    (_condition(quote="Nonprofits, universities, and state governments may apply."),
     _profile(), "lists multiple organization types"),
    (_condition("private foundation"), _profile(org_type="nonprofit"),
     "organization-type rule is ambiguous or unrecognized"),
    (_condition(), _profile(org_type=""), "profile's organization type"),
    (_condition(), _profile(org_type="unrecognized"), "profile's organization type"),
    (_condition("U.S.-based", ConditionType.LOCATION), _profile(us_based=None),
     "profile's U.S.-based status"),
    (_condition("U.S.-based", ConditionType.LOCATION), _profile(us_based="yes"),
     "profile's U.S.-based status"),
    (_condition("foreign and domestic organizations", ConditionType.LOCATION),
     _profile(), "location rule is ambiguous"),
    (_condition("specified region", ConditionType.LOCATION),
     _profile(), "location rule is ambiguous"),
    (_condition("small business"), _profile(org_type="for_profit"), "profile's size band"),
    (_condition("small business", ConditionType.SIZE),
     _profile(org_type="for_profit", size_band="unrecognized"), "profile's size band"),
    (_condition("small business", ConditionType.SIZE), _profile(),
     "profile's organization type"),
    (_condition("small business", ConditionType.SIZE),
     _profile(org_type="nonprofit", size_band="small"), "does not establish small-business status"),
    (_condition("fewer than 100 employees", ConditionType.SIZE), _profile(),
     "size rule is not a supported"),
    (_condition("", quote="Only nonprofits may apply."), _profile(), "no usable rule value"),
    (_condition(quote=""), _profile(), "no source quote to verify"),
])
def test_unknown_rule_or_profile_has_actionable_reason(condition, profile, explanation):
    row = match([condition], profile, "synthetic")
    assert row.verdict == Verdict.CHECK
    assert explanation in row.check_reasons[0]
    assert row.disqualifying_quotes == []


def test_unrecognized_polarity_has_reason():
    condition = _condition()
    condition.polarity = "uncertain"
    row = match([condition], _profile(org_type="nonprofit"), "synthetic")
    assert row.verdict == Verdict.CHECK
    assert "recognized requirement or exclusion" in row.check_reasons[0]


@pytest.mark.parametrize("quote", ["", "Invented source sentence."])
@pytest.mark.parametrize("keep_verified", [False, True])
def test_quote_verification_reason_without_showing_unverified_quote(quote, keep_verified):
    source = "Only nonprofits may apply."
    extracted = [_condition(quote=quote)]
    if keep_verified:
        extracted.append(_condition(quote=source))
    verified = verify_conditions(extracted, source)
    row = match(verified.verified, _profile(org_type="nonprofit"), "synthetic",
                unverified=[condition for condition, _ in verified.dropped])
    assert row.verdict == Verdict.CHECK
    assert len(row.check_reasons) == 1
    assert "Source quote verification failed" in row.check_reasons[0]
    assert "No eligibility conditions were extracted" not in row.check_reasons[0]
    assert row.check_quotes == []
    assert row.disqualifying_quotes == []


def test_multiple_review_reasons_are_stable_and_deduplicated():
    alternative = _condition("nonprofit or university")
    partnership = _condition("A partner is required.", ConditionType.PARTNERSHIP_REQUIRED)
    conditions = [alternative, partnership, alternative, partnership]
    profile = _profile(org_type="nonprofit")
    row = match(conditions, profile, "synthetic")
    assert row.verdict == Verdict.CHECK
    assert len(row.check_reasons) == 2
    assert "OR alternatives" in row.check_reasons[0]
    assert "partnership" in row.check_reasons[1]
    assert row.check_reasons == match(conditions, profile, "synthetic").check_reasons
    assert row.check_quotes == [alternative.quote, partnership.quote]


def test_citizenship_classified_foreign_entity_rule_still_requires_review():
    condition = _condition("Foreign organizations", ConditionType.CITIZENSHIP_OR_RESIDENCY)
    row = match([condition], _profile(us_based=True), "synthetic")
    assert row.verdict == Verdict.CHECK
    assert "citizenship or residency" in row.check_reasons[0]
    assert row.disqualifying_quotes == []


def test_verdict_row_roundtrip_preserves_reasons_and_existing_fields():
    row = VerdictRow(
        "synthetic", "synthetic-profile", Verdict.CHECK,
        disqualifying_quotes=["Existing disqualifier."],
        check_quotes=["Read this requirement."],
        conditions=[_condition()], override="CHECK",
        proposed_disqualifier_quotes=["Proposed quote."], latency_ms=12.5,
        check_reasons=["A manual review is needed.", "Confirm the profile's size."],
    )
    payload = json.loads(json.dumps(row.to_dict()))
    assert VerdictRow.from_dict(payload) == row
    assert cards.rows_to_verdictrows([payload]) == [row]
    assert json.loads(cards.verdictrows_to_jsonl([payload])) == payload


@pytest.mark.parametrize("reasons", [None, []])
def test_legacy_rows_and_optional_reasons_remain_compatible(reasons):
    payload = {"opportunity_id": "synthetic", "profile_id": "synthetic-profile",
               "verdict": "CHECK"}
    old_row = VerdictRow.from_dict(payload)
    payload["check_reasons"] = reasons
    assert VerdictRow.from_dict(payload) == old_row
    assert cards.rows_to_verdictrows([payload]) == [old_row]
    assert old_row.check_reasons == []
    old_row.check_reasons.append("Review this notice.")
    assert VerdictRow.from_dict(payload).check_reasons == []


@pytest.fixture
def render(monkeypatch):
    monkeypatch.setattr(cards, "_ACTIVE_CONFIG", {"card": {"max_rows_per_verdict": 40}})
    profile = _profile(org_type="nonprofit")
    return lambda rows: cards.render_card(profile, rows, {})


@pytest.mark.parametrize("override,reason", [
    (None, "No eligibility conditions were extracted"),
    ("CHECK", "manual override set this result to CHECK"),
    ("invalid", "manual override is unrecognized"),
])
def test_printable_card_explains_check_even_without_quotes(render, override, reason):
    row = match([], _profile(), "synthetic", override=override)
    output = render([row.to_dict()])
    assert row.check_quotes == []
    assert "Why CHECK:" in output
    assert reason in output
    assert "No sentence to read recorded" not in output


def test_printable_card_escapes_reasons_and_keeps_verified_quotes(render):
    reason = '<script>alert("review")</script> & confirm the profile'
    quote = "Applicants must have a partner."
    row = VerdictRow("synthetic", "synthetic-profile", Verdict.CHECK,
                     check_quotes=[quote], check_reasons=[reason])
    output = render([row.to_dict()])
    assert reason not in output
    assert html.escape(reason, quote=True) in output
    assert f'<mark class="marker-quote">{quote}</mark>' in output


def test_printable_legacy_check_has_useful_fallback(render):
    row = VerdictRow("synthetic", "synthetic-profile", Verdict.CHECK)
    output = render([row])
    assert "Why CHECK:" in output
    assert "Review the original notice against the profile" in output


@pytest.mark.parametrize("polarity,verdict", [
    (Polarity.REQUIRED, Verdict.ELIGIBLE),
    (Polarity.EXCLUDED, Verdict.NOT_ELIGIBLE),
])
def test_decisive_verdict_does_not_gain_review_reason(render, polarity, verdict):
    condition = _condition(quote=("Only nonprofits may apply." if polarity == Polarity.REQUIRED
                                  else "Nonprofits may not apply."))
    condition.polarity = polarity
    row = match([condition], _profile(org_type="nonprofit"), "synthetic")
    assert row.verdict == verdict
    assert row.check_reasons == []
    assert "Why CHECK:" not in render([row])
