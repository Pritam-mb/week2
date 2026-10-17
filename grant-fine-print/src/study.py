"""Headline numbers for the study (numbers (a) and (c), and the sample for (b)).

- (a) opportunities whose *only* applicant type is the "Others" code ("25").
- (b) opportunities whose codes look permissive but whose free text adds a
  hard disqualifier. (b) is hand-labelled, so this module only writes the
  random stratified sample sheet and never fabricates a label.
- (c) how many opportunities a simple keyword search for exclusion words
  catches, using ``config.study.exclusion_keywords`` as regexes over the
  eligibility text.

All counts are raw ("k of N"), per the PRD.
"""

from __future__ import annotations

import argparse
import csv
import os
import random
import re
from datetime import date
from typing import Any

from .config import get, load_config
from .io_utils import load_opportunities, write_json
from .models import Opportunity

OTHERS_CODE = "25"

HARD_DISQUALIFIER = (
    "A hard disqualifier is a sentence that says who may not apply, or that "
    "restricts applicants by location, organisation type, status or size."
)

SAMPLE_COLUMNS = [
    "opportunity_id",
    "title",
    "agency",
    "applicant_types",
    "seed",
    "label",
]


def _codes(opportunity: Opportunity) -> set[str]:
    return {str(code).strip() for code in opportunity.applicant_types}


def _only_others(opportunity: Opportunity) -> bool:
    """True when "25" is the sole applicant-type code."""
    return _codes(opportunity) == {OTHERS_CODE}


def _has_others(opportunity: Opportunity) -> bool:
    return OTHERS_CODE in _codes(opportunity)


def _has_permissive(opportunity: Opportunity) -> bool:
    codes = _codes(opportunity)
    return bool(codes) and OTHERS_CODE not in codes


def _keyword_patterns(config: dict[str, Any]) -> list[re.Pattern[str]]:
    keywords = get(config, "study.exclusion_keywords", default=[]) or []
    patterns: list[re.Pattern[str]] = []
    for keyword in keywords:
        try:
            patterns.append(re.compile(keyword, re.IGNORECASE))
        except re.error:
            continue
    return patterns


def _keyword_hit(text: str, patterns: list[re.Pattern[str]]) -> bool:
    return any(pattern.search(text or "") for pattern in patterns)


def _stratified_sample(
    opportunities: list[Opportunity], sample_size: int, seed: int
) -> list[Opportunity]:
    """~Half the sample with "25" in applicant_types, half permissive codes."""
    rng = random.Random(seed)
    with_others = [o for o in opportunities if _has_others(o)]
    permissive = [o for o in opportunities if _has_permissive(o)]
    rng.shuffle(with_others)
    rng.shuffle(permissive)

    half = sample_size // 2
    chosen = with_others[:half] + permissive[: sample_size - half]

    if len(chosen) < sample_size:
        chosen_ids = {id(o) for o in chosen}
        remaining = [o for o in opportunities if id(o) not in chosen_ids]
        rng.shuffle(remaining)
        chosen += remaining[: sample_size - len(chosen)]

    rng.shuffle(chosen)
    return chosen[:sample_size]


def _sample_row(opportunity: Opportunity, seed: int) -> dict[str, Any]:
    return {
        "opportunity_id": opportunity.id,
        "title": opportunity.title,
        "agency": opportunity.agency,
        "applicant_types": "|".join(str(code) for code in opportunity.applicant_types),
        "seed": seed,
        "label": "",
    }


def compute(
    opportunities: list[Opportunity],
    config: dict[str, Any],
    pull_date: str | None = None,
) -> dict[str, Any]:
    """Compute the study numbers and the stratified sample (no file writes)."""
    total = len(opportunities)
    patterns = _keyword_patterns(config)

    a_ids = [o.id for o in opportunities if _only_others(o)]
    c_ids = [o.id for o in opportunities if _keyword_hit(o.eligibility_text, patterns)]

    seed = int(get(config, "study.random_seed", default=0) or 0)
    requested = int(get(config, "study.sample_size", default=0) or 0)
    sample = _stratified_sample(opportunities, requested, seed) if requested > 0 else []

    return {
        "pull_date": pull_date or date.today().isoformat(),
        "total": total,
        "a_count": len(a_ids),
        "a_ids": a_ids,
        "a_raw": f"{len(a_ids)} of {total}",
        "c_count": len(c_ids),
        "c_ids": c_ids,
        "c_raw": f"{len(c_ids)} of {total}",
        "sample_size": len(sample),
        "seed": seed,
        "sample": [_sample_row(o, seed) for o in sample],
        "hard_disqualifier": HARD_DISQUALIFIER,
    }


def write_sample_sheet(result: dict[str, Any], config: dict[str, Any]) -> str:
    """Write the hand-labelling sample sheet (empty ``label`` column)."""
    path = get(config, "study.sample_path", default="data/samples/study_sample.csv")
    parent = os.path.dirname(os.path.abspath(path))
    os.makedirs(parent, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=SAMPLE_COLUMNS)
        writer.writeheader()
        for row in result.get("sample", []):
            writer.writerow({column: row.get(column, "") for column in SAMPLE_COLUMNS})
    return path


def write_study_json(result: dict[str, Any], config: dict[str, Any]) -> str:
    results_dir = get(config, "study.results_dir", default="results")
    os.makedirs(results_dir, exist_ok=True)
    path = os.path.join(results_dir, "study.json")
    write_json(path, result)
    return path


def summarize_labels(config: dict[str, Any]) -> dict[str, Any] | None:
    """Summarise the hand-applied (b) labels, if the labels file exists.

    The label file is produced by a human reading each sampled opportunity's
    free text; this function only aggregates it. Returns ``None`` when the
    file is absent so callers can tell "not yet labelled" from "zero".
    """
    path = get(config, "study.labels_path", default="data/labels/study_labels.csv")
    if not path or not os.path.exists(path):
        return None

    rows: list[dict[str, str]] = []
    with open(path, newline="", encoding="utf-8") as handle:
        rows = [row for row in csv.DictReader(handle) if row.get("opportunity_id")]

    def yes(row: dict[str, str]) -> bool:
        return str(row.get("hard_disqualifier", "")).strip().upper().startswith("Y")

    permissive = [r for r in rows if r.get("group") == "permissive"]
    others = [r for r in rows if r.get("group") == "others_only"]
    no_text = [r for r in rows if "empty" in r.get("note", "").lower()]
    return {
        "labelled": len(rows),
        "permissive_total": len(permissive),
        "permissive_with_disqualifier": sum(1 for r in permissive if yes(r)),
        "others_total": len(others),
        "others_with_disqualifier": sum(1 for r in others if yes(r)),
        "rows_with_no_eligibility_text": len(no_text),
        "labels_path": path,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Compute study headline numbers")
    parser.parse_args(argv)

    config = load_config()
    raw_dir = get(config, "cache.raw_dir", default="data/raw")
    opportunities = load_opportunities(raw_dir)

    result = compute(opportunities, config)
    sample_path = write_sample_sheet(result, config)
    result["sample_path"] = sample_path
    b = summarize_labels(config)
    if b is not None:
        result["b"] = b
    study_path = write_study_json(result, config)

    print(
        f"pull_date={result['pull_date']} total={result['total']} "
        f"a={result['a_raw']} c={result['c_raw']}"
    )
    if b is not None:
        print(
            f"b: permissive {b['permissive_with_disqualifier']} of "
            f"{b['permissive_total']} with hard disqualifier; "
            f"others-only {b['others_with_disqualifier']} of {b['others_total']}; "
            f"no-text rows {b['rows_with_no_eligibility_text']}"
        )
    print(f"sample: {sample_path}")
    print(f"study: {study_path}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
