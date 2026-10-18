"""Grants.gov source adapter implementing BaseSourceAdapter."""

from __future__ import annotations

from typing import Any

from .base import BaseSourceAdapter
from src.models import Opportunity


class GrantsGovAdapter(BaseSourceAdapter):
    """Adapter for official US Federal opportunities from Grants.gov REST API."""

    source_name = "grants_gov"
    display_name = "Grants.gov (US Federal)"
    default_country = "US"

    def pull(self, config: dict[str, Any], mock: bool = False) -> list[Opportunity]:
        from src.pull import _pull_grants_gov
        return _pull_grants_gov(config, mock=mock)
