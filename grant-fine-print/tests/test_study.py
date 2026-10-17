"""Tests for the study headline numbers."""

from __future__ import annotations

import re

from src.models import Opportunity
from src.study import compute

KEYWORDS = [
    "not eligible",
    "ineligible",
    "only .* may apply",
    "must be",
    "restricted to",
    "limited to",
    "excluded",
]


def _mk(index: int, applicant_types: list[str], eligibility_text: str) -> Opportunity:
    return Opportunity(
        id=f"o{index}",
        opp_number=f"n{index}",
        title=f"Title {index}",
        agency="HHS",
        applicant_types=applicant_types,
        eligibility_text=eligibility_text,
        synopsis="",
    )


def _config() -> dict:
    return {
        "study": {
            "sample_size": 6,
            "random_seed": 7,
            "exclusion_keywords": KEYWORDS,
            "results_dir": "results",
        }
    }


def _opportunities() -> list[Opportunity]:
    return [
        _mk(1, ["25"], "Only U.S. organizations may apply."),
        _mk(2, ["25"], "Nonprofits are eligible."),
        _mk(3, ["12"], "Applicants must be located in Ohio."),
        _mk(4, ["23"], "Small businesses are eligible."),
        _mk(5, ["12", "25"], "Only U.S. nonprofits may apply."),
        _mk(6, ["22", "12"], "For-profit organizations are not eligible."),
    ]


def test_a_counts_only_others_code() -> None:
    result = compute(_opportunities(), _config())
    assert result["a_count"] == 2
    assert result["a_ids"] == ["o1", "o2"]


def test_c_matches_regex_count() -> None:
    opportunities = _opportunities()
    result = compute(opportunities, _config())

    expected = sum(
        1
        for opp in opportunities
        if any(
            re.search(keyword, opp.eligibility_text, re.IGNORECASE) for keyword in KEYWORDS
        )
    )
    assert result["c_count"] == expected
    assert result["c_count"] == 4


def test_sample_is_stratified_and_has_empty_labels() -> None:
    result = compute(_opportunities(), _config())
    assert result["sample_size"] == 6
    assert len(result["sample"]) == 6
    assert all(row["label"] == "" for row in result["sample"])
    assert all("seed" in row for row in result["sample"])


def test_raw_counts_are_strings() -> None:
    result = compute(_opportunities(), _config())
    assert result["a_raw"] == "2 of 6"
    assert result["c_raw"] == "4 of 6"
