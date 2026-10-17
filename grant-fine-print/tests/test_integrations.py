"""Tests for optional production integrations and their trust boundaries."""

from __future__ import annotations

from src.discovery import SerpApiLinkFinder, is_official_grants_url
from src.models import Opportunity
from src.pipeline import _has_remote


def test_only_https_grants_domains_are_official() -> None:
    assert is_official_grants_url("https://grants.gov/opportunity/1")
    assert is_official_grants_url("https://apply07.grants.gov/details")
    assert not is_official_grants_url("http://grants.gov/opportunity/1")
    assert not is_official_grants_url("https://example.com/grants.gov")


def test_serpapi_is_noop_without_key(monkeypatch) -> None:
    monkeypatch.delenv("SERPAPI_KEY", raising=False)
    opportunity = Opportunity(id="1", opp_number="ABC-1", title="Health grant")
    assert SerpApiLinkFinder(api_key=None).discover(opportunity) == []


def test_existing_official_link_skips_search() -> None:
    opportunity = Opportunity(
        id="1",
        opp_number="ABC-1",
        title="Health grant",
        link="https://grants.gov/opportunity/1",
    )
    assert SerpApiLinkFinder(api_key="not-used").discover(opportunity) == []


def test_remote_requires_key_and_finetuned_model(monkeypatch) -> None:
    monkeypatch.setenv("TINKER_API_KEY", "secret")
    config = {"extract": {"provider_base_url": "https://example.test"}}
    assert _has_remote(config, "prompted")
    assert not _has_remote(config, "fine_tuned")
    config["extract"]["fine_tuned_model"] = "tinker://run/sampler_weights/1"
    assert _has_remote(config, "fine_tuned")
