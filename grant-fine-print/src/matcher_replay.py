"""Offline, post-hoc matcher diagnostic; never imports the inference pipeline.

Bootstrap with --legacy-cache data/extract_cache, then use --snapshot from the
output to repeat using only the public evidence bundle and exported conditions.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

from . import eval as evaluator
from .evidence_bundle import (
    SECRET, bundle_files, digest, public_bytes, validate_inputs, write_json,
)
from .match import evaluate_condition, match
from .models import Condition, Profile, text_hash
from .verify import verify_conditions


BACKENDS = {"prompted": "OpenAICompatibleBackend", "fine_tuned": "FineTunedBackend"}
CONDITION_FIELDS = {"type", "polarity", "value", "quote"}
CODE_FILES = ("match.py", "models.py", "verify.py", "eval.py", "matcher_replay.py",
              "evidence_bundle.py", "source_rules.py")


def sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def canonical_hash(value) -> str:
    return sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                             separators=(",", ":"), allow_nan=False).encode("utf-8"))


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def read_json(path):
    # Legacy envelopes may contain private metadata. Never copy their bytes.
    def invalid_constant(value):
        raise ValueError(f"invalid JSON constant: {value}")

    return json.loads(Path(path).read_text(encoding="utf-8"),
                      object_pairs_hook=_unique_object, parse_constant=invalid_constant)


def conditions_from_list(rows, context):
    """Require the entire list schema before constructing any replay input.

    Extra legacy metadata is deliberately projected away. Empty lists and empty
    string values/quotes are valid raw historical extractions, not cache misses;
    the current verifier/matcher determines their meaning.
    """
    if not isinstance(rows, list):
        raise ValueError(f"conditions must be a list: {context}")
    result = []
    for row in rows:
        if (not isinstance(row, dict) or not CONDITION_FIELDS <= row.keys() or
                any(not isinstance(row[field], str) for field in CONDITION_FIELDS)):
            raise ValueError(f"missing required fields or non-string condition: {context}")
        allowed = {field: row[field] for field in CONDITION_FIELDS}
        if SECRET.search(json.dumps(allowed, ensure_ascii=False)):
            raise ValueError(f"possible credential in condition: {context}")
        try:
            result.append(Condition.from_dict(allowed))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"invalid condition enum: {context}") from exc
    return result


def load_evidence(bundle):
    """Check original provenance and exact coverage before eval can intersect it."""
    bundle = Path(bundle)
    manifest = read_json(bundle / "provenance.json")
    if manifest.get("schema_version") != 1 or manifest.get("files") != bundle_files(bundle):
        raise ValueError("evidence SHA256/file inventory mismatch")
    labels, profile_paths, originals, sources = validate_inputs(
        bundle / "data/labels.csv", bundle / "data/profiles", bundle / "predictions",
        bundle / "data/test_sample.csv", bundle / "data/rubric.md")
    if set(originals) != {"code_only", *BACKENDS}:
        raise ValueError("original prediction systems must cover code_only, prompted, fine_tuned")
    if (manifest.get("notices"), manifest.get("profiles"), manifest.get("pairs")) != (
            len(sources), len(profile_paths), len(labels)):
        raise ValueError("evidence dimensions/coverage mismatch")
    profiles = {pid: Profile.from_dict(read_json(path)) for pid, path in profile_paths.items()}
    source_keys = [text_hash(source) for source in sources.values()]
    if len(source_keys) != len(set(source_keys)):
        raise ValueError("duplicate notice source hash")
    return labels, profiles, originals, sources


def make_snapshot(sources, evidence_hash, legacy_cache):
    """Read ONLY the source-keyed legacy files required for this evidence set."""
    records, cache_hashes = {}, {}
    for oid, source in sorted(sources.items()):
        key = text_hash(source)
        systems = {}
        for system, backend in BACKENDS.items():
            relative = f"{backend}/{key[:12]}.json"
            path = Path(legacy_cache) / relative
            if not path.is_file() or path.is_symlink():
                raise ValueError(f"missing legacy cache: {relative} ({oid})")
            data = read_json(path)
            if not isinstance(data, dict) or data.get("hash") != key:
                raise ValueError(f"legacy cache full source hash mismatch: {relative}")
            if data.get("opportunity_id") != oid:
                raise ValueError(f"legacy cache opportunity_id mismatch: {relative}")
            if data.get("backend") != backend or data.get("cache_key") != key[:12]:
                raise ValueError(f"legacy cache envelope mismatch: {relative}")
            raw = conditions_from_list(data.get("conditions"), relative)
            rows = [condition.to_dict() for condition in raw]
            systems[system] = {"conditions": rows, "conditions_sha256": canonical_hash(rows)}
            cache_hashes[relative] = digest(path)
        records[key] = {"opportunity_id": oid,
                        "source_sha256": sha256(source.encode("utf-8")), "systems": systems}
    return {"schema_version": 1, "evidence_provenance_sha256": evidence_hash,
            "sources": records}, cache_hashes


def validate_snapshot(snapshot, sources, evidence_hash):
    """Validate hashes, identity, schema and exact source/system coverage."""
    if (not isinstance(snapshot, dict) or set(snapshot) != {
            "schema_version", "evidence_provenance_sha256", "sources"} or
            snapshot["schema_version"] != 1 or
            snapshot["evidence_provenance_sha256"] != evidence_hash):
        raise ValueError("snapshot schema/evidence provenance hash mismatch")
    expected = {text_hash(source): (oid, source) for oid, source in sources.items()}
    records = snapshot["sources"]
    if not isinstance(records, dict) or set(records) != set(expected):
        raise ValueError("snapshot source coverage mismatch")
    raw_by_system = {system: {} for system in BACKENDS}
    for key, (oid, source) in sorted(expected.items()):
        record = records[key]
        if (not isinstance(record, dict) or set(record) != {
                "opportunity_id", "source_sha256", "systems"} or
                record["opportunity_id"] != oid or
                record["source_sha256"] != sha256(source.encode("utf-8"))):
            raise ValueError(f"snapshot source hash/opportunity_id mismatch: {key}")
        systems = record["systems"]
        if not isinstance(systems, dict) or set(systems) != set(BACKENDS):
            raise ValueError(f"snapshot system coverage mismatch: {oid}")
        for system, entry in systems.items():
            if not isinstance(entry, dict) or set(entry) != {"conditions", "conditions_sha256"}:
                raise ValueError(f"snapshot condition schema mismatch: {oid}/{system}")
            raw = conditions_from_list(entry["conditions"], f"{oid}/{system}")
            # Snapshots are strictly allowlisted, unlike private legacy envelopes.
            if any(set(row) != CONDITION_FIELDS for row in entry["conditions"]):
                raise ValueError(f"non-allowlisted snapshot condition fields: {oid}/{system}")
            if canonical_hash(entry["conditions"]) != entry["conditions_sha256"]:
                raise ValueError(f"snapshot conditions hash mismatch: {oid}/{system}")
            raw_by_system[system][oid] = raw
    return raw_by_system


def replay_rows(sources, profiles, raw_by_system):
    """Run current verify -> match, preserving pre-verifier proposed quotes."""
    expected = {(oid, pid) for oid in sources for pid in profiles}
    predictions, dropped = {}, {}
    for system in BACKENDS:
        raw_by_opp = raw_by_system[system]
        if set(raw_by_opp) != set(sources):
            raise ValueError(f"raw condition coverage mismatch: {system}")
        rows, counts = [], {}
        for oid, source in sorted(sources.items()):
            raw = raw_by_opp[oid]
            verified = verify_conditions(raw, source)
            counts[oid] = len(verified.dropped)
            for pid, profile in sorted(profiles.items()):
                proposed = [cond.quote for cond in raw
                            if cond.quote and evaluate_condition(cond, profile) == "conflict"]
                row = match(verified.verified, profile, oid,
                            unverified=[cond for cond, _ in verified.dropped])
                row.proposed_disqualifier_quotes = proposed
                row.latency_ms = None
                rows.append(row.to_dict())
        validate_coverage(rows, expected, system)
        predictions[f"replay_{system}"] = rows
        dropped[system] = counts
    return predictions, dropped


def validate_coverage(rows, expected, context):
    keys = [(row["opportunity_id"], row["profile_id"]) for row in rows]
    if len(keys) != len(set(keys)):
        raise ValueError(f"duplicate prediction pair: {context}")
    if set(keys) != expected:
        raise ValueError(f"prediction coverage mismatch: {context}")


def compare_originals(metrics, originals, predictions):
    comparisons = {}
    for system in BACKENDS:
        replay_name = f"replay_{system}"
        original_name = f"original_{system}"
        before = originals[system]
        changes = []
        for row in predictions[replay_name]:
            key = (row["opportunity_id"], row["profile_id"])
            old = before[key]["verdict"]
            if old != row["verdict"]:
                changes.append({"opportunity_id": key[0], "profile_id": key[1],
                                "original": old, "replay": row["verdict"]})
        deltas = {}
        for metric, entry in metrics["systems"][replay_name].items():
            if isinstance(entry, dict) and "rate" in entry:
                old = metrics["systems"][original_name][metric]["rate"]
                new = entry["rate"]
                deltas[metric] = None if old is None or new is None else new - old
        comparisons[system] = {"original": original_name, "replay": replay_name,
                               "rate_deltas_replay_minus_original": deltas,
                               "verdict_changes": changes, "changed_pairs": len(changes)}
    return comparisons


def replay_markdown(metrics, notices, profiles):
    lines = ["# Offline matcher replay", "",
             f"Post-hoc diagnostic on **{notices} notices x {profiles} constructed profiles "
             f"= {notices * profiles} pairs** from the original public evidence bundle.", "",
             "## Interpretation and limits", "",
             "- This is a reused development set with single-author labels, not an untouched "
             "holdout. Pairs share notices and profiles; they are not independent observations.",
             "- Cached extractions have unverifiable model identity: legacy backend class names "
             "do not authenticate a model, checkpoint, prompt, or training run. Replay uses "
             "those cached conditions with current quote verification and matching only.",
             "- This is not new inference, a fine-tuning improvement estimate, or a "
             "generalization claim. Changes cannot be attributed solely to fine-tuning.",
             "- Only labels' source_text and bundled profiles feed matching; label verdicts "
             "and sentences are used only by the canonical evaluator for scoring. "
             "No matching rules are fitted to labels. No overrides are applied.",
             "- `code_only` is copied byte-for-byte from original public predictions. "
             "`original_*` are also byte-for-byte copies; `replay_*` are separate outputs. "
             "Original latency remains historical. Replay latency_ms is null; no inference "
             "timing or cost is measured. Evaluation uses an empty metric config.", "",
             "## Metrics", "",
             "| System | Accuracy | Missed eligible grants | Human CHECK | "
             "Disqualified -> eligible | Automatic accuracy |",
             "|---|---:|---:|---:|---:|---:|"]
    for name, result in sorted(metrics["systems"].items()):
        counts = [f"{result[m]['k']}/{result[m]['n']}" for m in
                  ("accuracy", "missed_grant_rate", "human_read_share",
                   "disqualified_to_eligible_error", "automatic_decision_accuracy")]
        lines.append(f"| {name} | " + " | ".join(counts) + " |")
    lines += ["", "Full canonical metrics: `eval.json` and `eval_report.html`. "
              "`comparison.json` records rate deltas and all verdict changes.", "",
              "## Offline reproduction", "", "From the project root:", "", "```text",
              "python -B -m src.matcher_replay --bundle results/evidence "
              "--legacy-cache data/extract_cache --output results/matcher_replay",
              "python -B -m src.matcher_replay --bundle results/evidence "
              "--snapshot results/matcher_replay/conditions_snapshot.json "
              "--output results/matcher_replay_snapshot", "```", "",
              "Use a fresh output directory outside existing replay artifacts. "
              "Every run also rereads its exported snapshot and compares replay predictions, "
              "verifier drop counts and metrics in memory before recording successful "
              "snapshot roundtrip verification. Snapshot mode needs only this snapshot, "
              "the unchanged evidence bundle, and local Python code; no legacy cache, "
              "provider, credentials, config loader, or remote inference is used.", "",
              "## Hashes and privacy", "",
              "`conditions_snapshot.json` is keyed by the full SHA256 of whitespace-normalized "
              "source text (the historical cache key). Each notice also records the SHA256 "
              "of exact UTF-8 source text. Per-system conditions_sha256 hashes compact, "
              "sorted-key, UTF-8 JSON of the complete raw condition list before verification. "
              "Empty cached lists remain explicit; missing/corrupt entries fail closed.", "",
              "The snapshot allowlists notice IDs, hashes, system names, and condition "
              "type/polarity/value/quote only. Provider URLs, keys, checkpoint metadata, "
              "logs, and other cache fields are excluded. `provenance.json` records source "
              "and condition hashes, input file hashes, original evidence provenance hash, "
              "current code hashes (including match/models/verify), dropped-condition counts, "
              "and output hashes. Hashes establish consistency, not external authenticity.", ""]
    return "\n".join(lines)


def run_replay(bundle, output, *, legacy_cache=None, snapshot_path=None):
    if (legacy_cache is None) == (snapshot_path is None):
        raise ValueError("choose exactly one of legacy_cache or snapshot_path")
    bundle, output = Path(bundle), Path(output)
    if output.exists():
        raise ValueError(f"output already exists: {output}")
    protected = [bundle] + ([Path(legacy_cache)] if legacy_cache is not None else [])
    if any(output.resolve().is_relative_to(path.resolve()) for path in protected):
        raise ValueError("output must be separate from evidence and legacy cache")
    labels, profiles, originals, sources = load_evidence(bundle)
    evidence_hash = digest(bundle / "provenance.json")
    cache_hashes = {}
    if legacy_cache is not None:
        snapshot, cache_hashes = make_snapshot(sources, evidence_hash, legacy_cache)
    else:
        snapshot = read_json(snapshot_path)
    raw = validate_snapshot(snapshot, sources, evidence_hash)
    predictions, dropped = replay_rows(sources, profiles, raw)
    expected = set(labels)
    for system, rows in originals.items():
        name = "code_only" if system == "code_only" else f"original_{system}"
        predictions[name] = list(rows.values())
    for name, rows in predictions.items():
        validate_coverage(rows, expected, name)
    # Metrics are always the existing evaluator's, with no config loader call.
    metrics = {"systems": {name: evaluator.evaluate_system(rows, labels, {})
                           for name, rows in sorted(predictions.items())}}
    metrics["comparison"] = evaluator.compare_systems(metrics)
    comparisons = compare_originals(metrics, originals, predictions)

    output.mkdir(parents=True)
    prediction_dir = output / "predictions"
    prediction_dir.mkdir()
    for name, rows in sorted(predictions.items()):
        path = prediction_dir / f"{name}.jsonl"
        if name.startswith("replay_"):
            path.write_text("".join(json.dumps(row, ensure_ascii=False, allow_nan=False) + "\n"
                                    for row in rows), encoding="utf-8")
        else:
            original = name.removeprefix("original_")
            path.write_bytes(public_bytes(bundle / "predictions" / f"{original}.jsonl"))
    write_json(output / "conditions_snapshot.json", snapshot)
    # Exercise the persisted public snapshot, independently of legacy envelopes.
    restored = validate_snapshot(read_json(output / "conditions_snapshot.json"),
                                 sources, evidence_hash)
    roundtrip_rows, roundtrip_dropped = replay_rows(sources, profiles, restored)
    for name, rows in roundtrip_rows.items():
        if (rows != predictions[name] or
                evaluator.evaluate_system(rows, labels, {}) != metrics["systems"][name]):
            raise ValueError(f"persisted snapshot replay mismatch: {name}")
    if roundtrip_dropped != dropped:
        raise ValueError("persisted snapshot verifier counts mismatch")
    write_json(output / "eval.json", metrics)
    write_json(output / "comparison.json", comparisons)
    (output / "eval_report.html").write_text(evaluator.render_report(metrics), encoding="utf-8")
    (output / "REPLAY.md").write_text(
        replay_markdown(metrics, len(sources), len(profiles)), encoding="utf-8")
    input_names = ["data/labels.csv", "provenance.json"]
    input_names += [f"data/profiles/{path.name}"
                    for path in sorted((bundle / "data/profiles").glob("*.json"))]
    input_names += [f"predictions/{name}.jsonl" for name in originals]
    code_root = Path(__file__).parent
    write_json(output / "provenance.json", {
        "schema_version": 1, "diagnostic": "post-hoc reused development set matcher replay",
        "inference_rerun": False, "model_identity_verified": False, "metric_config": {},
        "snapshot_roundtrip_verified": True,
        "notices": len(sources), "profiles": len(profiles), "pairs": len(labels),
        "mode": "legacy-cache" if legacy_cache is not None else "snapshot",
        "evidence_provenance_sha256": evidence_hash,
        "inputs_sha256": {name: digest(bundle / name) for name in sorted(input_names)},
        "snapshot_input_sha256": digest(snapshot_path) if snapshot_path is not None else None,
        "legacy_cache_files_sha256": cache_hashes,
        "sources": {key: {"opportunity_id": record["opportunity_id"],
                          "source_sha256": record["source_sha256"],
                          "conditions_sha256": {system: entry["conditions_sha256"]
                                                for system, entry in record["systems"].items()}}
                    for key, record in snapshot["sources"].items()},
        "code_sha256": {f"src/{name}": digest(code_root / name) for name in CODE_FILES},
        "verifier_dropped_conditions": dropped,
        "files": bundle_files(output),
    })
    return metrics


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, default=Path("results/evidence"))
    inputs = parser.add_mutually_exclusive_group(required=True)
    inputs.add_argument("--legacy-cache", type=Path, help="legacy extraction cache root")
    inputs.add_argument("--snapshot", type=Path, help="exported conditions_snapshot.json")
    parser.add_argument("--output", type=Path, default=Path("results/matcher_replay"))
    args = parser.parse_args(argv)
    try:
        metrics = run_replay(args.bundle, args.output, legacy_cache=args.legacy_cache,
                             snapshot_path=args.snapshot)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    for name, result in metrics["systems"].items():
        print(f"{name}: accuracy {result['accuracy']['k']}/{result['accuracy']['n']}, "
              f"CHECK {result['human_read_share']['k']}/{result['human_read_share']['n']}")
    print(f"Wrote {args.output}; offline diagnostic only, no inference")
    return 0


if __name__ == "__main__":
    sys.exit(main())
