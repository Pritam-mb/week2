"""Optional SerpApi discovery for missing official Grants.gov links.

SerpApi is deliberately outside the eligibility path. Its title/snippet is
stored as discovery metadata only; ``Opportunity.source_text`` always comes
from the official Grants.gov payload.
"""

from __future__ import annotations

import argparse
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from urllib.parse import urlparse

import requests
from dotenv import load_dotenv

from .models import Opportunity


@dataclass(frozen=True)
class OfficialLinkCandidate:
    opportunity_id: str
    query: str
    url: str
    title: str
    snippet: str
    position: int | None
    is_official: bool
    discovered_at: str


def is_official_grants_url(url: str) -> bool:
    parsed = urlparse(url or "")
    host = (parsed.hostname or "").lower().rstrip(".")
    return parsed.scheme == "https" and (
        host == "grants.gov" or host.endswith(".grants.gov")
    )


class SerpApiLinkFinder:
    def __init__(
        self,
        api_key: str | None = None,
        timeout: float = 15,
        engine: str = "google",
        endpoint: str = "https://serpapi.com/search.json",
    ):
        self.api_key = api_key or os.environ.get("SERPAPI_KEY")
        self.timeout = timeout
        self.engine = engine
        self.endpoint = endpoint

    def discover(self, opportunity: Opportunity, num: int = 10) -> list[OfficialLinkCandidate]:
        if opportunity.link and is_official_grants_url(opportunity.link):
            return []
        if not self.api_key:
            return []
        clean_num = (opportunity.opp_number or "").strip()
        if clean_num:
            query = f'site:grants.gov "{clean_num}"'
        else:
            words = [w for w in (opportunity.title or "").split() if len(w) > 3][:6]
            query = f"site:grants.gov {' '.join(words)}" if words else "site:grants.gov"

        response = requests.get(
            self.endpoint,
            params={
                "engine": self.engine,
                "q": query,
                "api_key": self.api_key,
                "num": num,
            },
            timeout=self.timeout,
        )
        response.raise_for_status()
        data = response.json()
        now = datetime.now(timezone.utc).isoformat()
        candidates: list[OfficialLinkCandidate] = []
        for index, result in enumerate(data.get("organic_results", []) or [], 1):
            if not isinstance(result, dict):
                continue
            url = str(result.get("link") or "")
            candidates.append(
                OfficialLinkCandidate(
                    opportunity_id=opportunity.id,
                    query=query,
                    url=url,
                    title=str(result.get("title") or ""),
                    snippet=str(result.get("snippet") or ""),
                    position=index,
                    is_official=is_official_grants_url(url),
                    discovered_at=now,
                )
            )
        return candidates


def enrich_opportunity_link(
    opportunity: Opportunity,
    finder: SerpApiLinkFinder | None = None,
    store: Any = None,
) -> str | None:
    """Attempt to discover an official Grants.gov link if missing.

    Returns the discovered official URL if found, else None.
    Never alters source_text or eligibility decisions.
    """
    if opportunity.link and is_official_grants_url(opportunity.link):
        return opportunity.link
    finder = finder or SerpApiLinkFinder()
    candidates = finder.discover(opportunity)
    official_candidates = [c for c in candidates if c.is_official]
    if not official_candidates:
        return None
    best = official_candidates[0]
    opportunity.link = best.url
    if store is not None and hasattr(store, "save_link_candidate"):
        try:
            store.save_link_candidate(
                {
                    "opportunity_id": opportunity.id,
                    "query": best.query,
                    "url": best.url,
                    "title": best.title,
                    "snippet": best.snippet,
                    "position": best.position,
                    "is_official": True,
                    "selected": True,
                }
            )
        except Exception:
            pass
    return best.url


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    parser = argparse.ArgumentParser(prog="python -m src.discovery")
    parser.add_argument("--opportunity-number", required=True)
    parser.add_argument("--title", required=True)
    parser.add_argument("--id", default="discovery")
    args = parser.parse_args(argv)
    opportunity = Opportunity(
        id=args.id,
        opp_number=args.opportunity_number,
        title=args.title,
    )
    finder = SerpApiLinkFinder()
    for candidate in finder.discover(opportunity):
        print(asdict(candidate))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
