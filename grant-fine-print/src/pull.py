"""Pull open grant opportunities from the Grants.gov public API and cache them.

Public interface
----------------
``pull(config, mock=False) -> list[Opportunity]``
``main(argv=None)``  -- CLI: ``python -m src.pull [--mock] [--out data/raw]``

Assumptions about the Grants.gov API (documented because the live response
schema can drift; the code degrades gracefully when names differ)
-------------------------------------------------------------------------
* Base URL and paths come from ``config.api.base_url``,
  ``config.api.search2_path`` and ``config.api.fetch_opportunity_path``.
* ``POST {base_url}{search2_path}`` takes a JSON body with
  ``startRecordNum``, ``oppStatuses``, ``rows``, ``sortBy`` and
  ``searchFields`` (the configured field list). The response is expected to be
  ``{"hitCount": int, "oppHits": [...]}``; a bare list or an
  ``{"opportunities": [...]}`` wrapper is also accepted.
* ``POST {base_url}{fetch_opportunity_path}`` takes ``{"oppId": <id>}`` and
  returns the opportunity detail object (possibly wrapped).
* Detail field names follow the configured ``search_fields`` list
  (``oppNumber``, ``oppTitle``, ``agencyName``, ``oppStatus``, ``openDate``,
  ``closeDate``, ``awardFloor``, ``awardCeiling``, ``awardEstimate``,
  ``costSharing``, ``applicantTypes``, ``synopsisDesc``,
  ``eligibilityCriteria``). In practice Grants.gov often nests
  ``synopsisDesc``/``eligibilityCriteria`` inside a ``synopsis`` object, so
  lookups also search that container. Unknown or missing names become empty
  strings / empty lists rather than raising.

No authentication is required. Requests are rate-limited and retried with a
small exponential backoff.
"""

from __future__ import annotations

import argparse
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

from .config import get, load_config
from .io_utils import (
    load_manifest,
    opportunity_from_raw,
    read_json,
    write_json,
    write_manifest,
)
from .models import Opportunity, normalize_ws, text_hash

DEFAULT_ROWS = 100


class _Client:
    """Thin, polite wrapper around a requests.Session."""

    def __init__(self, config: dict) -> None:
        self.config = config
        self.session = requests.Session()
        self.session.headers.update(
            {"Accept": "application/json", "Content-Type": "application/json"}
        )
        self._last_request = 0.0

    def _interval(self) -> float:
        value = get(self.config, "api.min_request_interval_seconds", 1.0)
        try:
            return max(0.0, float(value))
        except (TypeError, ValueError):
            return 1.0

    def _timeout(self) -> float:
        value = get(self.config, "api.timeout_seconds", 30)
        try:
            return float(value)
        except (TypeError, ValueError):
            return 30.0

    def _retries(self) -> int:
        value = get(self.config, "api.max_retries", 3)
        try:
            return max(0, int(value))
        except (TypeError, ValueError):
            return 3

    def post(self, url: str, body: dict) -> Any:
        return self._request(url, json_body=body)

    def post_form(self, url: str, fields: dict) -> Any:
        """POST as application/x-www-form-urlencoded (the legacy detail API)."""
        return self._request(url, form_body=fields)

    def _request(
        self,
        url: str,
        json_body: dict | None = None,
        form_body: dict | None = None,
    ) -> Any:
        interval = self._interval()
        wait = interval - (time.monotonic() - self._last_request)
        if wait > 0:
            time.sleep(wait)

        last_error: Exception | None = None
        for attempt in range(self._retries() + 1):
            if attempt:
                time.sleep(min(0.5 * (2**attempt), 5.0))
            try:
                if form_body is not None:
                    response = self.session.post(
                        url,
                        data=form_body,
                        headers={"Content-Type": "application/x-www-form-urlencoded"},
                        timeout=self._timeout(),
                    )
                else:
                    response = self.session.post(
                        url, json=json_body, timeout=self._timeout()
                    )
                if response.status_code in (429,) or response.status_code >= 500:
                    last_error = RuntimeError(
                        f"HTTP {response.status_code} from {url}"
                    )
                    continue
                response.raise_for_status()
                self._last_request = time.monotonic()
                return response.json()
            except (requests.RequestException, ValueError) as exc:
                last_error = exc
        raise last_error or RuntimeError(f"request to {url} failed")


def _base_url(config: dict) -> str:
    return str(get(config, "api.base_url", "https://api.grants.gov/v1/api")).rstrip("/")


def _unwrap_hits(data: Any) -> tuple[list[dict], int | None]:
    """Return (hits, hit_count) from a search2 response of any known shape."""
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)], None
    if isinstance(data, dict):
        # The live API wraps results in {"data": {...}}.
        if isinstance(data.get("data"), dict):
            data = data["data"]
        hit_count = data.get("hitCount")
        for key in ("oppHits", "hits", "opportunities", "results"):
            value = data.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)], hit_count
    return [], None


def _search_hits(client: _Client, config: dict, search_fields: list[str]) -> list[dict]:
    """Page through search2 until hitCount is reached (or the safety cap)."""
    url = _base_url(config) + str(get(config, "api.search2_path", "/search2"))
    rows = int(get(config, "api.page_rows", DEFAULT_ROWS) or DEFAULT_ROWS)
    statuses = str(get(config, "api.opp_statuses", "posted"))
    max_opps = int(get(config, "api.max_opportunities", 0) or 0)

    hits: list[dict] = []
    start = 0
    total: int | None = None
    while True:
        body: dict[str, Any] = {
            "startRecordNum": start,
            # Grants.gov expects a pipe-string; a JSON list silently returns 0.
            "oppStatuses": statuses,
            "sortBy": "openDate|desc",
            "rows": rows,
        }
        if search_fields:
            body["searchFields"] = list(search_fields)
        page, hit_count = _unwrap_hits(client.post(url, body))
        if total is None:
            total = hit_count
        if not page:
            break
        hits.extend(page)
        start += rows
        if max_opps and len(hits) >= max_opps:
            break
        if total is not None and start >= total:
            break
    return hits[:max_opps] if max_opps else hits


def _fetch_detail(client: _Client, config: dict, opp_id: str, search_fields: list[str]) -> dict | None:
    """Fetch one opportunity detail.

    Prefers the legacy Grants.gov service, which is reachable directly and
    returns the free-text eligibility field. Falls back to the documented
    ``fetchOpportunity`` path (whose backend is often unavailable).
    """
    legacy = get(config, "api.legacy_detail_url")
    if legacy:
        try:
            data = client.post_form(str(legacy), {"oppId": opp_id})
            if _looks_like_detail(data):
                return data
        except Exception:
            pass

    body: dict[str, Any] = {"oppId": opp_id, "searchFields": list(search_fields)}
    url = _base_url(config) + str(
        get(config, "api.fetch_opportunity_path", "/fetchOpportunity")
    )
    try:
        data = client.post(url, body)
    except Exception:
        return None
    if isinstance(data, dict):
        for key in ("opportunity", "details", "data"):
            nested = data.get(key)
            if isinstance(nested, dict) and _looks_like_detail(nested):
                return nested
        if _looks_like_detail(data):
            return data
    return None


def _looks_like_detail(data: Any) -> bool:
    if not isinstance(data, dict):
        return False
    if isinstance(data.get("synopsis"), dict) or isinstance(data.get("forecast"), dict):
        return True
    return any(
        key in data
        for key in ("opportunityNumber", "opportunityTitle", "applicantTypes")
    )


def _merge_hit_and_detail(hit: dict, detail: dict | None) -> dict:
    """Overlay the search hit's identity/date fields onto the detail payload."""
    raw: dict[str, Any] = dict(detail) if isinstance(detail, dict) else {}
    for source, target in (
        ("id", "id"),
        ("number", "oppNumber"),
        ("title", "oppTitle"),
        ("agency", "agencyName"),
        ("oppStatus", "oppStatus"),
        ("openDate", "openDate"),
        ("closeDate", "closeDate"),
    ):
        if hit.get(source) is not None:
            raw[target] = hit[source]
    return raw


def _project_root(config: dict) -> Path:
    root = config.get("_project_root")
    return Path(root) if root else Path.cwd()


def _mock_sample_path(config: dict) -> Path:
    return _project_root(config) / "data" / "samples" / "mock_opportunities.json"


def _load_mock_details(config: dict) -> list[dict]:
    """Load the offline sample file, or synthesise data if it is absent."""
    path = _mock_sample_path(config)
    if path.exists():
        data = read_json(path)
        if isinstance(data, list):
            return [item for item in data if isinstance(item, dict)]
        if isinstance(data, dict):
            for key in ("oppHits", "opportunities"):
                value = data.get(key)
                if isinstance(value, list):
                    return [item for item in value if isinstance(item, dict)]
            return [data]
    return _synthesize_opportunities()


def _synthesize_opportunities() -> list[dict]:
    """~8 realistic synthetic opportunities, offline-friendly."""
    templates = [
        (
            "MOCK-001",
            "Community Health Outreach Program",
            "HHS",
            ["25", "12", "13"],
            "Eligibility is open to all applicant types, including Others. "
            "No geographic or organisational restriction applies.",
        ),
        (
            "MOCK-002",
            "Rural Broadband Expansion Grant",
            "USDA",
            ["00", "01", "02", "25"],
            "Only state, county and municipal governments may apply. "
            "For-profit entities are ineligible.",
        ),
        (
            "MOCK-003",
            "Tribal Language Preservation Award",
            "Interior",
            ["07", "11"],
            "Restricted to federally recognized tribal governments and "
            "native American tribal organizations.",
        ),
        (
            "MOCK-004",
            "Small Business Innovation Research",
            "NSF",
            ["23", "22"],
            "Open to small businesses and for-profit organizations. "
            "Universities may not be the prime applicant.",
        ),
        (
            "MOCK-005",
            "Public University Research Fellowship",
            "DOE",
            ["06", "20"],
            "Eligible applicants are public and private institutions of "
            "higher education.",
        ),
        (
            "MOCK-006",
            "Individual Artist Residency",
            "NEA",
            ["21"],
            "Individuals are eligible to apply. Organizations are not "
            "eligible for this program.",
        ),
        (
            "MOCK-007",
            "Statewide Workforce Development",
            "DOL",
            ["00", "04", "25"],
            "State governments and special district governments are "
            "eligible; Other applicants may apply where permitted.",
        ),
        (
            "MOCK-008",
            "Nonprofit Capacity Building Fund",
            "FEMA",
            ["12", "13", "25"],
            "Open to 501(c)(3) and other nonprofits, including Others. "
            "Government agencies are not eligible.",
        ),
    ]
    details: list[dict] = []
    for opp_id, title, agency, codes, eligibility in templates:
        details.append(
            {
                "id": opp_id,
                "oppNumber": opp_id,
                "oppTitle": title,
                "agencyName": agency,
                "oppStatus": "posted",
                "openDate": "2026-01-10",
                "closeDate": "2026-04-10",
                "awardFloor": 25000,
                "awardCeiling": 300000,
                "awardEstimate": 100000,
                "costSharing": False,
                "applicantTypes": [{"code": code, "label": code} for code in codes],
                "synopsis": {
                    "synopsisDesc": f"Synopsis for {title}.",
                    "eligibilityCriteria": eligibility,
                },
                "oppHttps": f"https://grants.gov/view-opportunity?oppId={opp_id}",
            }
        )
    return details


def _cache_prefix(text_hash_value: str, length: int) -> str:
    if not text_hash_value:
        return "0" * length
    return text_hash_value[:length]


def _known_hashes(manifest: dict) -> dict[str, str]:
    known: dict[str, str] = {}
    for entry in manifest.get("files", []) or []:
        if not isinstance(entry, dict):
            continue
        opp_id = entry.get("id")
        if opp_id is None:
            continue
        known[str(opp_id)] = str(entry.get("hit_hash") or entry.get("text_hash") or "")
    return known


def _known_final_hashes(manifest: dict) -> set[str]:
    values = manifest.get("opportunities", {}) or {}
    if isinstance(values, dict):
        return {str(v) for v in values.values() if v}
    return set()


def _known_files(manifest: dict) -> dict[str, str]:
    """Map opportunity id -> cached filename from the manifest."""
    files: dict[str, str] = {}
    for entry in manifest.get("files", []) or []:
        if isinstance(entry, dict) and entry.get("id") is not None:
            files[str(entry["id"])] = str(entry.get("file") or "")
    return files


def _hit_fingerprint(hit: dict) -> str:
    """Stable hash of the search-hit fields, to detect changed opportunities.

    The search hit carries no eligibility text, so this can only detect
    changes Grants.gov reflects in these fields (status, dates, title).
    """
    fields = ("id", "number", "title", "agency", "oppStatus", "openDate", "closeDate")
    return text_hash("|".join(str(hit.get(field) or "") for field in fields))


def pull(config: dict, mock: bool = False) -> list[Opportunity]:
    """Pull, cache and de-duplicate open opportunities.

    When ``mock`` is true the offline sample (or synthetic) data is used and
    no network request is made. Returns the unique opportunities in pull order.
    """
    raw_dir = Path(str(get(config, "cache.raw_dir", "data/raw")))
    manifest_path = Path(
        str(get(config, "cache.manifest", str(raw_dir / "manifest.json")))
    )
    prefix_length = int(get(config, "cache.hash_prefix_length", 12) or 12)
    search_fields = [str(f) for f in (get(config, "api.search_fields", []) or [])]

    raw_dir.mkdir(parents=True, exist_ok=True)
    manifest = load_manifest(manifest_path)
    known_hit = _known_hashes(manifest)
    known_final = _known_final_hashes(manifest)
    known_files = _known_files(manifest)

    total_pulled = 0
    unchanged = 0
    fetched: list[dict] = []

    if mock:
        raw_details = _load_mock_details(config)
        total_pulled = len(raw_details)
        for raw in raw_details:
            provisional = opportunity_from_raw(raw, search_fields)
            opp_id = provisional.id or provisional.opp_number
            if not opp_id:
                continue
            fetched.append(
                {
                    "id": opp_id,
                    "hit_hash": provisional.text_hash,
                    "raw": raw,
                }
            )
    else:
        client = _Client(config)
        hits = _search_hits(client, config, search_fields)
        total_pulled = len(hits)
        for hit in hits:
            hit_hash = _hit_fingerprint(hit)
            opp_id = str(hit.get("id") or hit.get("number") or "").strip()
            if not opp_id:
                continue
            # Reuse the cached payload when the hit fingerprint is unchanged.
            if (
                hit_hash
                and known_hit.get(opp_id) == hit_hash
                and known_files.get(opp_id)
            ):
                cached = read_json(raw_dir / known_files[opp_id])
                if isinstance(cached, dict):
                    unchanged += 1
                    fetched.append(
                        {
                            "id": opp_id,
                            "hit_hash": hit_hash,
                            "raw": cached,
                            "cached": True,
                        }
                    )
                    continue
            detail = _fetch_detail(client, config, opp_id, search_fields)
            if detail is None:
                continue
            fetched.append(
                {
                    "id": opp_id,
                    "hit_hash": hit_hash,
                    "raw": _merge_hit_and_detail(hit, detail),
                }
            )

    unique: list[Opportunity] = []
    files: list[dict] = []
    seen_hash: set[str] = set()
    seen_eligibility: set[str] = set()
    new_count = 0
    changed_count = 0
    duplicate_count = 0

    for candidate in fetched:
        raw = candidate["raw"]
        opp = opportunity_from_raw(raw, search_fields)
        if not opp.id:
            opp.id = candidate["id"]
        if not opp.link:
            opp.link = f"https://grants.gov/search-results-detail/{opp.id}"

        if candidate.get("cached"):
            # Already cached and unchanged: include it, write nothing.
            unique.append(opp)
            files.append(
                {
                    "id": opp.id,
                    "file": known_files.get(str(opp.id), ""),
                    "text_hash": opp.text_hash,
                    "hit_hash": candidate["hit_hash"],
                }
            )
            continue

        current_hash = opp.text_hash
        eligibility = normalize_ws(opp.eligibility_text)

        if (current_hash and current_hash in seen_hash) or (
            eligibility and eligibility in seen_eligibility
        ):
            duplicate_count += 1
            continue

        if current_hash:
            seen_hash.add(current_hash)
        if eligibility:
            seen_eligibility.add(eligibility)

        prefix = _cache_prefix(candidate["hit_hash"] or current_hash, prefix_length)
        filename = f"{opp.id}__{prefix}.json"
        write_json(raw_dir / filename, raw)
        write_json(
            raw_dir / f"{opp.id}__{prefix}.fetched",
            {"id": opp.id, "text_hash": current_hash},
        )

        if str(opp.id) in known_final or str(opp.id) in known_hit:
            changed_count += 1
        else:
            new_count += 1

        files.append(
            {
                "id": opp.id,
                "file": filename,
                "text_hash": current_hash,
                "hit_hash": candidate["hit_hash"],
            }
        )
        unique.append(opp)

    pull_date = datetime.now(timezone.utc).isoformat()
    write_manifest(
        manifest_path,
        pull_date=pull_date,
        total_pulled=total_pulled,
        new=new_count,
        changed=changed_count,
        duplicates=duplicate_count + unchanged,
        files=files,
    )
    return unique


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Pull open grants from Grants.gov.")
    parser.add_argument("--mock", action="store_true", help="use offline sample data")
    parser.add_argument("--out", default=None, help="override the raw cache directory")
    parser.add_argument("--config", default="config.yaml", help="path to config.yaml")
    args = parser.parse_args(argv)

    config = load_config(args.config)
    if args.out:
        config.setdefault("cache", {})["raw_dir"] = str(Path(args.out).resolve())
    elif args.mock:
        # Keep the offline sample cache separate from the live cache so a mock
        # pull can never mix with real Grants.gov data.
        root = Path(str(config.get("_project_root") or Path.cwd()))
        config.setdefault("cache", {})["raw_dir"] = str((root / "data" / "mock_raw").resolve())
        config["cache"]["manifest"] = str(
            (root / "data" / "mock_raw" / "manifest.json").resolve()
        )

    opportunities = pull(config, mock=args.mock)
    print(f"pulled {len(opportunities)} opportunities (mock={args.mock})")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
