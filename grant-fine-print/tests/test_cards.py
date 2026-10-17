"""Tests for the printable card renderer."""

from __future__ import annotations

from src.cards import render_card
from src.models import Opportunity, Profile, Verdict, VerdictRow


def _fixture():
    profile = Profile(id="p1", name="Acme Nonprofit", org_type="nonprofit")
    opp = Opportunity(
        id="o1",
        opp_number="ABC-123",
        title="Rural Health Grant",
        agency="HHS",
        close_date="2026-12-31",
        award_floor=10000,
        award_ceiling=50000,
        link="https://grants.gov/view/opportunity/ABC-123",
    )
    not_eligible = VerdictRow(
        opportunity_id="o1",
        profile_id="p1",
        verdict=Verdict.NOT_ELIGIBLE,
        disqualifying_quotes=["Only U.S.-based organizations are eligible."],
    )
    check = VerdictRow(
        opportunity_id="o1",
        profile_id="p1",
        verdict=Verdict.CHECK,
        check_quotes=["Applicants must demonstrate prior experience."],
    )
    return profile, opp, [not_eligible, check]


def test_render_card_contains_required_content():
    profile, opp, rows = _fixture()
    html_out = render_card(profile, rows, {"o1": opp})

    for needle in (
        "Acme Nonprofit",
        "ABC-123",
        "Only U.S.-based organizations are eligible.",
        "NOT ELIGIBLE",
        "CHECK",
        "Confirm in the original notice.",
    ):
        assert needle in html_out, f"missing: {needle!r}"
    assert '<meta name="viewport"' in html_out
    assert '<meta name="description"' in html_out
    assert "overflow-wrap: anywhere" in html_out


def test_render_card_is_escaped():
    profile, opp, rows = _fixture()
    opp.title = "<script>alert(1)</script>"
    html_out = render_card(profile, rows, {"o1": opp})
    assert "<script>alert(1)</script>" not in html_out
    assert "&lt;script&gt;" in html_out


def test_render_card_respects_max_rows():
    profile, opp, rows = _fixture()
    rows = [rows[0]] * 45 + [rows[1]]
    html_out = render_card(profile, rows, {"o1": opp})
    assert "and 5 more" in html_out


def test_render_card_shows_provenance():
    profile, opp, rows = _fixture()
    html_out = render_card(
        profile,
        rows,
        {"o1": opp},
        provenance={"backend": "MockBackend", "pull_date": "2026-10-17T12:00:00Z"},
    )
    assert "Extraction: MockBackend" in html_out
    assert "Pulled 2026-10-17T12:00:00Z" in html_out
