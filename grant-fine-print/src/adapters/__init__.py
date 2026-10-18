"""Source adapters package for multi-source and multi-country grant ingestion."""

from __future__ import annotations

from typing import Any

from .base import BaseSourceAdapter
from .grants_gov import GrantsGovAdapter
from .eu_funding import EUFundingAdapter

_REGISTRY: dict[str, type[BaseSourceAdapter]] = {
    "grants_gov": GrantsGovAdapter,
    "grantsgov": GrantsGovAdapter,
    "eu_funding": EUFundingAdapter,
}


def register_adapter(name: str, adapter_cls: type[BaseSourceAdapter]) -> None:
    """Register a new source adapter."""
    _REGISTRY[name.lower()] = adapter_cls


def get_adapter(name: str = "grants_gov") -> BaseSourceAdapter:
    """Instantiate and return the configured source adapter."""
    cls = _REGISTRY.get((name or "grants_gov").lower(), GrantsGovAdapter)
    return cls()


def available_sources() -> list[dict[str, str]]:
    """Return metadata about registered source adapters."""
    return [
        {
            "id": "grants_gov",
            "name": "Grants.gov (US Federal)",
            "country": "US",
            "active": True,
        },
        {
            "id": "eu_funding",
            "name": "EU Funding & Tenders Portal",
            "country": "EU",
            "active": True,
        },
        {
            "id": "canada_grants",
            "name": "Canada Grants & Funding",
            "country": "CA",
            "active": False,
        },
    ]


__all__ = [
    "BaseSourceAdapter",
    "GrantsGovAdapter",
    "EUFundingAdapter",
    "get_adapter",
    "register_adapter",
    "available_sources",
]
