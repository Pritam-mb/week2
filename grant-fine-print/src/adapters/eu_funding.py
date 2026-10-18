"""EU Funding & Tenders Portal adapter."""

from __future__ import annotations

from typing import Any
from pathlib import Path

import requests
from src.models import Opportunity
from .base import BaseSourceAdapter
from src.io_utils import clean_html


class EUFundingAdapter(BaseSourceAdapter):
    source_name = "eu_funding"
    display_name = "EU Funding & Tenders Portal"
    default_country = "EU"

    API_BASE = "https://ec.europa.eu/info/funding-tenders/opportunities/portal/api"

    def pull(self, config: dict[str, Any], mock: bool = False) -> list[Opportunity]:
        if mock:
            return self._load_mock(config)

        raw_dir = Path(str(config.get("cache", {}).get("raw_dir", "data/raw/eu_funding")))
        raw_dir.mkdir(parents=True, exist_ok=True)

        # Simple search – first 200 open opportunities
        # Adjust query params as needed for your scope
        params = {
            "api-version": "1.0",
            "$top": 200,
            "$select": "id,title,programmeCode,deadline,description,eligibility",
        }
        url = f"{self.API_BASE}/opportunities"
        resp = requests.get(url, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()

        opps = []
        for item in data.get("value", []):
            opp = Opportunity(
                id=str(item.get("id") or item.get("opportunityId")),
                opp_number=str(item.get("id")),
                title=clean_html(item.get("title", "")) or "",
                agency=clean_html(item.get("programmeCode", "")) or "EU Commission",
                status="posted",
                applicant_types=[],
                eligibility_text=clean_html(item.get("eligibility", "")) or "",
                synopsis=clean_html(item.get("description", "")) or "",
            )
            opps.append(opp)

        # Cache raw JSON
        manifest_path = Path(str(config.get("cache", {}).get("manifest", raw_dir / "manifest.json")))
        # Simple cache write omitted for brevity – keep same contract as GrantsGovAdapter
        return opps

    def _load_mock(self, config: dict[str, Any]) -> list[Opportunity]:
        # Minimal mock for local testing
        return [
            Opportunity(
                id="EU-TEST-001",
                opp_number="EU-TEST-001",
                title="Horizon Europe Test Call",
                agency="EU Commission",
                status="posted",
                applicant_types=[],
                eligibility_text="Eligible for entities established in EU Member States.",
                synopsis="Synthetic EU opportunity for adapter testing.",
            )
        ]
