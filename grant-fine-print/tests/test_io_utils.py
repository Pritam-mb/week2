"""Regression: cached raw Grants.gov payloads must load as opportunities.

The mock/cache files are camelCase API payloads (with a nested "synopsis"
object); they must go through opportunity_from_raw, not be silently dropped.
"""

from __future__ import annotations

import json
from pathlib import Path

from src.io_utils import load_opportunities, opportunity_from_raw
from src.models import Opportunity

RAW_PAYLOAD = {
    "id": "MOCK-001",
    "oppNumber": "MOCK-001",
    "oppTitle": "Community Health Outreach Program",
    "agencyName": "Department of Health and Human Services",
    "oppStatus": "posted",
    "openDate": "2026-01-10",
    "closeDate": "2026-04-10",
    "awardFloor": 25000,
    "awardCeiling": 300000,
    "costSharing": False,
    "applicantTypes": [{"code": "25", "label": "Others"}],
    "synopsis": {
        "synopsisDesc": "Funds community health outreach.",
        "eligibilityCriteria": "Eligibility is open to all applicant types.",
    },
    "oppHttps": "https://grants.gov/view-opportunity?oppId=MOCK-001",
}


def test_opportunity_from_raw_maps_camel_case():
    opp = opportunity_from_raw(RAW_PAYLOAD)
    assert opp.id == "MOCK-001"
    assert opp.title == "Community Health Outreach Program"
    assert opp.applicant_types == ["25"]
    assert "Eligibility is open" in opp.eligibility_text
    assert opp.award_ceiling == 300000


def test_load_opportunities_reads_raw_payload_file(tmp_path: Path):
    path = tmp_path / "MOCK-001.json"
    path.write_text(json.dumps(RAW_PAYLOAD), encoding="utf-8")
    opps = load_opportunities(tmp_path)
    assert len(opps) == 1
    assert opps[0].opp_number == "MOCK-001"


def test_opportunity_to_dict_roundtrips():
    opp = opportunity_from_raw(RAW_PAYLOAD)
    again = Opportunity.from_dict(opp.to_dict())
    assert again == opp
