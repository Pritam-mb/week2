"""Tests for multi-source adapter layer."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from src.adapters import (
    BaseSourceAdapter,
    GrantsGovAdapter,
    available_sources,
    get_adapter,
    register_adapter,
)
from src.config import load_config
from src.models import Opportunity

ROOT = Path(__file__).resolve().parents[1]


class DummyTestAdapter(BaseSourceAdapter):
    source_name = "dummy_portal"
    display_name = "Dummy Grant Portal"
    default_country = "TEST"

    def pull(self, config: dict[str, Any], mock: bool = False) -> list[Opportunity]:
        return [
            Opportunity(
                id="TEST-001",
                opp_number="TEST-001",
                title="Synthetic Test Opportunity",
                agency="Test Agency",
                status="posted",
                applicant_types=["25"],
                eligibility_text="Eligible for test entities only.",
                synopsis="Synthetic test synopsis.",
            )
        ]


def test_get_default_adapter() -> None:
    adapter = get_adapter()
    assert isinstance(adapter, GrantsGovAdapter)
    assert adapter.source_name == "grants_gov"
    assert adapter.default_country == "US"


def test_available_sources() -> None:
    sources = available_sources()
    assert len(sources) >= 3
    source_ids = [s["id"] for s in sources]
    assert "grants_gov" in source_ids
    assert "eu_funding" in source_ids
    assert "canada_grants" in source_ids


def test_custom_adapter_registration() -> None:
    register_adapter("dummy_portal", DummyTestAdapter)
    adapter = get_adapter("dummy_portal")
    assert isinstance(adapter, DummyTestAdapter)
    assert adapter.source_name == "dummy_portal"

    results = adapter.pull({}, mock=True)
    assert len(results) == 1
    assert results[0].id == "TEST-001"


def test_grants_gov_adapter_pull_mock(tmp_path: Path) -> None:
    config = load_config(str(ROOT / "config.yaml"))
    config.setdefault("cache", {})["raw_dir"] = str(tmp_path / "raw")
    config["cache"]["manifest"] = str(tmp_path / "raw" / "manifest.json")

    adapter = GrantsGovAdapter()
    opps = adapter.pull(config, mock=True)
    assert len(opps) >= 5
    assert all(isinstance(o, Opportunity) for o in opps)


def test_eu_funding_adapter_mock() -> None:
    from src.adapters import EUFundingAdapter
    adapter = get_adapter("eu_funding")
    assert isinstance(adapter, EUFundingAdapter)
    assert adapter.source_name == "eu_funding"
    assert adapter.default_country == "EU"

    opps = adapter.pull({}, mock=True)
    assert len(opps) >= 1
    assert opps[0].id == "EU-TEST-001"
    assert "EU Member States" in opps[0].eligibility_text
