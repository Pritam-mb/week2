"""Base abstraction for multi-source and multi-country grant ingestion.

Downstream verification, fine-tuned extraction, and matching are source-agnostic:
they only interact with normalized Opportunity and Profile dataclasses.
Specific portal APIs (Grants.gov, EU Funding & Tenders, Canada Grants) implement
this adapter contract.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from src.models import Opportunity


class BaseSourceAdapter(ABC):
    """Abstract interface that all grant source adapters must implement."""

    source_name: str = "base"
    display_name: str = "Base Source Adapter"
    default_country: str = "US"

    @abstractmethod
    def pull(self, config: dict[str, Any], mock: bool = False) -> list[Opportunity]:
        """Fetch, normalize, and cache opportunities from the source.

        Args:
            config: Runtime configuration dictionary.
            mock: If True, load offline sample/fixture without network calls.

        Returns:
            List of normalized Opportunity objects ready for extraction & screening.
        """
        raise NotImplementedError
