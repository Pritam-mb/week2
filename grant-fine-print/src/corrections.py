"""Per-profile, per-opportunity override memory (the MVP memory table).

A correction remembers a human's verdict for one (profile, opportunity) pair,
keyed as ``"profile_id|opportunity_id"``. Storage is a single JSON object;
writes are atomic so a crash cannot leave a half-written file.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DEFAULT_PATH = "data/corrections/corrections.json"
_SEP = "|"


def _key(profile_id: str, opportunity_id: str) -> str:
    return f"{profile_id}{_SEP}{opportunity_id}"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_corrections(path: str | Path = DEFAULT_PATH) -> dict[str, dict[str, Any]]:
    """Return the corrections mapping, or {} when the file is missing/bad."""
    p = Path(path)
    if not p.exists():
        return {}
    try:
        with p.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def apply_override(
    corrections: dict[str, dict[str, Any]], profile_id: str, opportunity_id: str
) -> str | None:
    """Return the override verdict for the pair, or None if there is none."""
    entry = corrections.get(_key(profile_id, opportunity_id))
    if not isinstance(entry, dict):
        return None
    verdict = entry.get("verdict")
    return verdict if isinstance(verdict, str) else None


def save_correction(
    path: str | Path,
    profile_id: str,
    opportunity_id: str,
    verdict: str,
    note: str = "",
) -> dict[str, Any]:
    """Append/upsert one correction with an ISO ``created_at`` timestamp."""
    p = Path(path)
    corrections = load_corrections(p)
    entry = {
        "verdict": verdict,
        "note": note,
        "created_at": _utc_now_iso(),
    }
    corrections[_key(profile_id, opportunity_id)] = entry
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        json.dump(corrections, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    tmp.replace(p)
    return entry


def corrections_summary(corrections: dict[str, dict[str, Any]]) -> dict[str, int]:
    """Count corrections by verdict (missing/blank verdicts counted as None)."""
    counts: dict[str, int] = {}
    for entry in corrections.values():
        verdict = entry.get("verdict") if isinstance(entry, dict) else None
        key = verdict if isinstance(verdict, str) else None
        counts[key] = counts.get(key, 0) + 1
    return counts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m src.corrections",
        description="Record a per-profile, per-opportunity override.",
    )
    parser.add_argument("--profile", required=True, help="profile id")
    parser.add_argument("--opportunity", required=True, help="opportunity id")
    parser.add_argument("--verdict", required=True, help="ELIGIBLE | NOT_ELIGIBLE | CHECK")
    parser.add_argument("--note", default="", help="optional note")
    parser.add_argument("--path", default=DEFAULT_PATH, help="corrections JSON path")
    args = parser.parse_args(argv)

    entry = save_correction(
        args.path, args.profile, args.opportunity, args.verdict, args.note
    )
    print(json.dumps(entry, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
