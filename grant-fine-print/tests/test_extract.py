"""Tests for the stage-1 extractor, focused on quote validity."""

from __future__ import annotations

import tempfile
from pathlib import Path

from src.extract import (
    EXTRACTION_PROMPT,
    EXTRACTION_SYSTEM,
    MockBackend,
    _load_opportunity_file,
    extract_conditions,
)
from src.models import ConditionType, Opportunity, Polarity

TEXT = (
    "Eligible applicants must be U.S.-based 501(c)(3) nonprofit organizations. "
    "For-profit organizations are not eligible to apply. "
    "Only small businesses may apply for this program."
)


def _opportunity() -> Opportunity:
    return Opportunity(
        id="test-1",
        opp_number="ABC-001",
        title="Test Opportunity",
        agency="HHS",
        applicant_types=["12"],
        eligibility_text=TEXT,
        synopsis="",
    )


def _config() -> dict:
    return {
        "cache": {"hash_prefix_length": 12},
        "extract": {"cache_dir": tempfile.mkdtemp(prefix="gfp-extract-test-")},
    }


def test_prompt_templates_exist() -> None:
    assert "conditions" in EXTRACTION_PROMPT
    assert "verbatim" in EXTRACTION_PROMPT.lower()
    assert "JSON" in EXTRACTION_PROMPT
    assert EXTRACTION_SYSTEM


def test_mock_backend_conditions_are_verbatim() -> None:
    opportunity = _opportunity()
    conditions = extract_conditions(opportunity, MockBackend(), _config())

    assert len(conditions) >= 1
    source = opportunity.source_text
    for condition in conditions:
        assert condition.quote
        assert condition.quote in source, condition.quote
        assert condition.type in ConditionType
        assert condition.polarity in Polarity


def test_mock_backend_is_deterministic_and_caches() -> None:
    opportunity = _opportunity()
    config = _config()
    first = extract_conditions(opportunity, MockBackend(), config)
    second = extract_conditions(opportunity, MockBackend(), config)
    assert [c.to_dict() for c in first] == [c.to_dict() for c in second]


def test_mock_backend_does_not_promote_program_description_to_eligibility() -> None:
    opportunity = Opportunity(
        id="descriptive-1",
        opp_number="ABC-002",
        title="Language Program",
        eligibility_text="This program supports tribal languages and university research.",
    )
    conditions = extract_conditions(opportunity, MockBackend(), _config())
    assert conditions == []


def test_cli_loads_nested_grants_payload(tmp_path: Path) -> None:
    path = tmp_path / "opportunity.json"
    path.write_text(
        '{"id":"O-1","oppNumber":"O-1","oppTitle":"Title",'
        '"synopsis":{"synopsisDesc":"Summary",'
        '"eligibilityCriteria":"Only nonprofits may apply."}}',
        encoding="utf-8",
    )
    opportunity = _load_opportunity_file(str(path))
    assert opportunity.title == "Title"
    assert opportunity.synopsis == "Summary"
    assert opportunity.eligibility_text == "Only nonprofits may apply."
