"""Filesystem helpers: JSON, text, JSONL, profiles, opportunities, manifest.

Everything here is stdlib-only apart from the shared models. The helpers are
deliberately forgiving about missing/``None`` fields so a single malformed
cached file never takes down a whole pull.
"""

from __future__ import annotations

import html as _html
import json
import re
from pathlib import Path
from typing import Any, Iterable

from .models import Opportunity, Profile, normalize_ws

_TAG_RE = re.compile(r"<[^>]+>")


def clean_html(text: Any) -> str:
    """Strip HTML tags and decode entities from Grants.gov free text."""
    if text is None:
        return ""
    return normalize_ws(_TAG_RE.sub(" ", _html.unescape(str(text))))

# Canonical API field name -> candidate keys, most-authoritative first. The
# nested containers are searched too (Grants.gov wraps much of the detail
# payload inside a "synopsis" object).
_FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "id": ("id", "oppId", "opportunityId"),
    "opp_number": ("opportunityNumber", "oppNumber", "opportunityNumber", "number"),
    "title": ("opportunityTitle", "oppTitle", "title"),
    "agency": ("agencyName", "agency"),
    "status": ("oppStatus", "status", "docType"),
    "open_date": ("openDate", "postingDateStr", "postingDate"),
    "close_date": ("closeDate", "responseDateStr", "responseDate"),
    "award_floor": ("awardFloor",),
    "award_ceiling": ("awardCeiling",),
    "award_estimate": ("estimatedFunding", "awardEstimate"),
    "cost_sharing": ("costSharing", "costSharingRequired"),
    "applicant_types": ("applicantTypes",),
    "synopsis": ("synopsisDesc", "forecastDesc", "synopsis"),
    "eligibility_text": (
        "applicantEligibilityDesc",
        "eligibilityCriteria",
        "eligibilityText",
    ),
    "link": ("oppHttps", "oppHttp", "link", "fundingDescLinkUrl"),
}

# Reverse lookup: an API field name -> the Opportunity attribute it feeds.
_TARGET_BY_NAME: dict[str, str] = {}
for _target, _names in _FIELD_ALIASES.items():
    for _name in _names:
        _TARGET_BY_NAME.setdefault(_name.lower(), _target)

_NESTED_CONTAINERS = ("synopsis", "forecast", "synopsistor")


# --------------------------------------------------------------------------- #
# Primitive IO
# --------------------------------------------------------------------------- #
def read_text(path: str | Path) -> str:
    """Read a UTF-8 text file. Returns an empty string if it is missing."""
    p = Path(path)
    if not p.exists():
        return ""
    try:
        return p.read_text(encoding="utf-8")
    except OSError:
        return ""


def write_text(path: str | Path, text: str) -> None:
    """Write UTF-8 text, creating parent directories as needed."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def read_json(path: str | Path, default: Any = None) -> Any:
    """Read a JSON file. Returns ``default`` if missing or invalid."""
    p = Path(path)
    if not p.exists():
        return default
    try:
        with p.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return default


def write_json(path: str | Path, data: Any) -> None:
    """Write ``data`` as UTF-8 JSON, creating parent directories as needed."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2, ensure_ascii=False)
        handle.write("\n")
    tmp.replace(p)


def read_jsonl(path: str | Path) -> list[dict]:
    """Read a JSONL file into a list of dicts, skipping blank/invalid lines."""
    records: list[dict] = []
    p = Path(path)
    if not p.exists():
        return records
    for line in read_text(p).splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(record, dict):
            records.append(record)
    return records


def append_jsonl(path: str | Path, record: dict) -> None:
    """Append one JSON object as a single line, creating parents as needed."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False))
        handle.write("\n")


# --------------------------------------------------------------------------- #
# Profiles
# --------------------------------------------------------------------------- #
def load_profiles(dir_or_file: str | Path | list[Any]) -> list[Profile]:
    """Load profiles from a directory, a single JSON file, or an in-memory list.

    Each ``*.json`` file in a directory is treated as one profile, except
    ``manifest.json``. A ``profiles.json`` file may instead hold a list of
    profiles or an object with a ``profiles`` key. Malformed files are skipped.
    """
    if isinstance(dir_or_file, (str, Path)):
        source = Path(dir_or_file)
        if source.is_file():
            files = [source]
        else:
            files = sorted(
                f for f in source.glob("*.json") if f.name != "manifest.json"
            )
        profiles: list[Profile] = []
        for path in files:
            data = read_json(path)
            if data is None:
                continue
            profiles.extend(_coerce_profiles(data))
        return profiles

    return _coerce_profiles(list(dir_or_file))


def _coerce_profiles(data: Any) -> list[Profile]:
    if isinstance(data, list):
        items = data
    elif isinstance(data, dict) and isinstance(data.get("profiles"), list):
        items = data["profiles"]
    elif isinstance(data, dict):
        items = [data]
    else:
        return []

    result: list[Profile] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        try:
            result.append(Profile.from_dict(item))
        except (TypeError, ValueError):
            continue
    return result


# --------------------------------------------------------------------------- #
# Opportunities / manifest
# --------------------------------------------------------------------------- #
def _lookup(raw: Any, key: str) -> Any:
    """Find ``key`` at the top level or inside a known nested container."""
    if not isinstance(raw, dict):
        return None
    containers: list[dict] = [raw]
    for name in _NESTED_CONTAINERS:
        nested = raw.get(name)
        if isinstance(nested, dict):
            containers.append(nested)

    for container in containers:
        if key in container and container[key] is not None:
            return container[key]
    lowered = key.lower()
    for container in containers:
        for name, value in container.items():
            if isinstance(name, str) and name.lower() == lowered and value is not None:
                return value
    return None


def _extract_codes(value: Any) -> list[str]:
    """Normalise applicant-type values to a list of code strings."""
    if value is None:
        return []
    codes: list[str] = []
    if isinstance(value, list):
        for item in value:
            if isinstance(item, dict):
                code = item.get("code") or item.get("value") or item.get("id")
                if code is None:
                    code = item.get("label") or item.get("name")
                if code is not None:
                    codes.append(str(code))
            elif item is not None:
                codes.append(str(item))
    elif isinstance(value, (str, int, float)):
        codes.append(str(value))
    return [code for code in codes if code]


def _to_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in {"true", "yes", "y", "1"}
    return False


def _to_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return float(value)
    cleaned = str(value).replace(",", "").replace("$", "").strip()
    try:
        return float(cleaned)
    except ValueError:
        return None


def opportunity_from_raw(
    raw: Any, search_fields: Iterable[str] | None = None
) -> Opportunity:
    """Build an :class:`Opportunity` from a raw Grants.gov detail payload.

    ``search_fields`` (from ``config.api.search_fields``) names the API fields
    to prefer. Any field that is absent or ``None`` degrades to an empty string
    / empty list / ``None`` rather than raising. Field names are matched
    case-insensitively and nested inside a ``synopsis`` object when present.
    """
    if not isinstance(raw, dict):
        raw = {}

    values: dict[str, Any] = {name: None for name in _FIELD_ALIASES}

    # Prefer the configured search fields first.
    if search_fields:
        for name in search_fields:
            target = _TARGET_BY_NAME.get(str(name).lower())
            if target and values.get(target) is None:
                values[target] = _lookup(raw, str(name))

    # Fall back to the full alias table.
    for target, names in _FIELD_ALIASES.items():
        if values.get(target) is None:
            for name in names:
                found = _lookup(raw, name)
                if found is not None:
                    values[target] = found
                    break

    return Opportunity(
        id=str(values.get("id") or ""),
        opp_number=str(values.get("opp_number") or ""),
        title=str(values.get("title") or ""),
        agency=str(values.get("agency") or ""),
        status=str(values.get("status") or ""),
        open_date=str(values.get("open_date") or ""),
        close_date=str(values.get("close_date") or ""),
        award_floor=_to_float(values.get("award_floor")),
        award_ceiling=_to_float(values.get("award_ceiling")),
        award_estimate=_to_float(values.get("award_estimate")),
        cost_sharing=_to_bool(values.get("cost_sharing")),
        applicant_types=_extract_codes(values.get("applicant_types")),
        synopsis=clean_html(values.get("synopsis")),
        eligibility_text=clean_html(values.get("eligibility_text")),
        link=str(values.get("link") or ""),
    )


def _looks_like_opportunity_dict(item: dict) -> bool:
    # A serialised Opportunity (Opportunity.to_dict()) always carries these
    # snake_case keys. Raw Grants.gov payloads are camelCase (and may also
    # contain a "synopsis" object), so they must go through
    # opportunity_from_raw() instead of Opportunity.from_dict().
    return "opp_number" in item or (
        "eligibility_text" in item and "applicant_types" in item
    )


def _coerce_opportunities(data: Any, search_fields: Iterable[str] | None = None) -> list[Opportunity]:
    if isinstance(data, list):
        items = data
    elif isinstance(data, dict) and isinstance(data.get("opportunities"), list):
        items = data["opportunities"]
    elif isinstance(data, dict) and isinstance(data.get("items"), list):
        items = data["items"]
    elif isinstance(data, dict):
        items = [data]
    else:
        return []

    result: list[Opportunity] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        try:
            if _looks_like_opportunity_dict(item):
                result.append(Opportunity.from_dict(item))
            else:
                result.append(opportunity_from_raw(item, search_fields))
        except (TypeError, ValueError):
            continue
    return result


def load_opportunities(
    dir_or_file: str | Path | list[Any],
    search_fields: Iterable[str] | None = None,
) -> list[Opportunity]:
    """Load cached raw opportunity JSON files from a directory or in-memory list.

    ``manifest.json`` is skipped. Each file is converted with
    :func:`opportunity_from_raw` when it looks like a raw API payload, or with
    ``Opportunity.from_dict`` when it already holds an Opportunity shape.
    """
    if isinstance(dir_or_file, (str, Path)):
        source = Path(dir_or_file)
        if source.is_file():
            files = [source]
        else:
            files = sorted(
                f for f in source.glob("*.json") if f.name != "manifest.json"
            )
        opportunities: list[Opportunity] = []
        for path in files:
            data = read_json(path)
            if data is None:
                continue
            opportunities.extend(_coerce_opportunities(data, search_fields))
        return opportunities

    return _coerce_opportunities(list(dir_or_file), search_fields)


def load_manifest(path: str | Path) -> dict:
    """Load ``manifest.json``; returns ``{}`` when missing or unreadable."""
    data = read_json(path)
    return data if isinstance(data, dict) else {}


def write_manifest(
    path: str | Path,
    pull_date: str,
    total_pulled: int,
    new: int,
    changed: int,
    duplicates: int,
    files: list[dict],
) -> dict:
    """Write the pull manifest and return the manifest dict.

    ``files`` is a list of ``{"id", "file", "text_hash"}`` entries. An
    ``opportunities`` id -> text_hash map is added for cheap re-pull checks.
    """
    entries = files if isinstance(files, list) else []
    manifest = {
        "pull_date": pull_date,
        "total_pulled": total_pulled,
        "new": new,
        "changed": changed,
        "duplicates": duplicates,
        "files": entries,
        "opportunities": {
            entry.get("id"): entry.get("text_hash")
            for entry in entries
            if isinstance(entry, dict) and entry.get("id") is not None
        },
    }
    write_json(path, manifest)
    return manifest
