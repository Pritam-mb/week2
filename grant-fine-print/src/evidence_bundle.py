"""Build and verify a portable, offline public-benchmark evidence directory.

Run ``python -m src.evidence_bundle build --help`` for input overrides.
Only explicitly allowlisted artifacts are copied; no environment/config loader,
provider client, raw opportunity cache, or inference pipeline is imported.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
import shutil
import sys
from pathlib import Path

from . import eval as evaluator
from .models import normalize_ws
from .verify import is_verbatim_quote


LABEL_FIELDS = set(evaluator.REQUIRED_LABEL_COLUMNS) | {"source_text", "rubric_note"}
PROFILE_FIELDS = {"id", "name", "org_type", "us_based", "state", "size_band",
                  "focus_keywords", "notes"}
PRED_FIELDS = {"opportunity_id", "profile_id", "verdict", "disqualifying_quotes",
               "check_quotes", "check_reasons", "conditions", "override",
               "proposed_disqualifier_quotes", "latency_ms"}
SAMPLE_FIELDS = {"opportunity_id", "opp_number", "title", "agency", "applicant_types"}
SAFE_ID = re.compile(r"[A-Za-z0-9_-]+\Z")
SECRET = re.compile(
    r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----|"
    r"\bBearer\s+[A-Za-z0-9._~+/=-]{12,}|\bsk-[A-Za-z0-9_-]{16,}|"
    r"(?i:(?:api[_-]?key|access[_-]?token|password|client[_-]?secret)"
    r"[\"']?\s*[:=]\s*[\"']?[^\s\"',}]{8,})"
)
CODE_FILES = ("__init__.py", "eval.py", "models.py", "verify.py", "evidence_bundle.py")
RERUN = "python -m src.evidence_bundle verify --bundle ."
EVAL_RERUN = (
    "python -m src.eval --config eval_config.json --labels data/labels.csv "
    "--predictions-dir predictions --out eval.rerun.json --report eval.rerun.html"
)


def public_bytes(path: Path) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"expected a regular public artifact: {path}")
    content = path.read_bytes()
    if SECRET.search(content.decode("utf-8")):
        raise ValueError(f"possible credential in public artifact: {path.name}")
    return content


def fields(actual, allowed, context):
    unknown = set(actual) - allowed
    if unknown:
        raise ValueError(f"non-public/unknown fields in {context}: {sorted(unknown)}")


def identifier(value):
    if not isinstance(value, str) or not SAFE_ID.fullmatch(value):
        raise ValueError(f"invalid public identifier: {value!r}")
    return value


def csv_rows(path, allowed):
    public_bytes(path)
    with path.open(encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        fields(reader.fieldnames or [], allowed, path.name)
        if len(reader.fieldnames or []) != len(set(reader.fieldnames or [])):
            raise ValueError(f"duplicate CSV columns: {path.name}")
        rows = list(reader)
    if not rows or any(None in row or None in row.values() for row in rows):
        raise ValueError(f"empty or malformed CSV: {path.name}")
    return rows


def validate_inputs(labels_path, profiles_dir, predictions_dir, sample_path, rubric):
    """Validate BEFORE src.eval can silently deduplicate/intersect pair sets."""
    records = csv_rows(labels_path, LABEL_FIELDS)
    keys = []
    sources = {}
    for row in records:
        key = (identifier(row["opportunity_id"]), identifier(row["profile_id"]))
        keys.append(key)
        source = row.get("source_text", "")
        if not source.strip():
            raise ValueError(f"missing public source_text for {key}")
        if sources.setdefault(key[0], source) != source:
            raise ValueError(f"inconsistent source_text for {key[0]}")
    if len(keys) != len(set(keys)):
        raise ValueError("duplicate label pair")
    labels = evaluator.load_labels(labels_path)
    opportunities = {key[0] for key in keys}
    profile_ids = {key[1] for key in keys}
    expected = {(o, p) for o in opportunities for p in profile_ids}
    if set(keys) != expected:
        raise ValueError("labels do not cover the notice x profile Cartesian product")

    profiles = {}
    for path in sorted(profiles_dir.glob("*.json")):
        profile = json.loads(public_bytes(path))
        if not isinstance(profile, dict):
            raise ValueError(f"profile must be an object: {path.name}")
        fields(profile, PROFILE_FIELDS, path.name)
        for name, value in profile.items():
            if name == "focus_keywords":
                valid = isinstance(value, list) and all(isinstance(v, str) for v in value)
            elif name == "us_based":
                valid = isinstance(value, bool)
            else:
                valid = isinstance(value, str)
            if not valid:
                raise ValueError(f"invalid public profile field {name} in {path.name}")
        pid = identifier(profile.get("id"))
        if pid in profiles:
            raise ValueError(f"duplicate profile: {pid}")
        profiles[pid] = path
    if set(profiles) != profile_ids:
        raise ValueError("profile JSON IDs do not exactly match label profile IDs")

    sample = csv_rows(sample_path, SAMPLE_FIELDS)
    sample_ids = [identifier(row["opportunity_id"]) for row in sample]
    if len(set(sample_ids)) != len(sample_ids) or set(sample_ids) != opportunities:
        raise ValueError("test sample IDs must be unique and exactly match labels")
    public_bytes(rubric)

    systems = {}
    for path in sorted(predictions_dir.glob("*.jsonl")):
        identifier(path.stem)
        public_bytes(path)
        rows = evaluator.load_predictions(path)
        seen = set()
        for row in rows:
            fields(row, PRED_FIELDS, path.name)
            key = (identifier(row["opportunity_id"]), identifier(row["profile_id"]))
            if key in seen:
                raise ValueError(f"duplicate prediction pair in {path.name}: {key}")
            seen.add(key)
            for name in ("disqualifying_quotes", "check_quotes", "check_reasons",
                         "proposed_disqualifier_quotes"):
                quotes = row.get(name)
                if quotes is not None and (not isinstance(quotes, list) or
                                           any(not isinstance(q, str) for q in quotes)):
                    raise ValueError(f"invalid {name} in {path.name}: {key}")
            conditions = row.get("conditions", [])
            if not isinstance(conditions, list):
                raise ValueError(f"invalid conditions in {path.name}")
            for condition in conditions:
                if not isinstance(condition, dict):
                    raise ValueError(f"invalid condition in {path.name}")
                fields(condition, {"type", "polarity", "value", "quote"}, path.name)
                if any(not isinstance(value, str) for value in condition.values()):
                    raise ValueError(f"invalid condition text in {path.name}")
            if row.get("override") is not None and not isinstance(row["override"], str):
                raise ValueError(f"invalid override in {path.name}")
            latency = row.get("latency_ms")
            if latency is not None and (isinstance(latency, bool) or
                                       not isinstance(latency, (int, float)) or
                                       not math.isfinite(latency)):
                raise ValueError(f"invalid latency in {path.name}")
        if seen != expected:
            raise ValueError(f"prediction coverage mismatch in {path.name}: "
                             f"missing={sorted(expected - seen)}, extra={sorted(seen - expected)}")
        systems[path.stem] = { (r["opportunity_id"], r["profile_id"]): r for r in rows }
    if not systems:
        raise ValueError("no prediction JSONL files")
    return labels, profiles, systems, sources


def worked_examples(labels, systems, baseline, fine_tuned):
    if baseline not in systems or fine_tuned not in systems or baseline == fine_tuned:
        raise ValueError("distinct baseline and fine-tuned prediction systems are required")
    base, tuned = systems[baseline], systems[fine_tuned]
    ordered = sorted(labels)
    misses = [k for k in ordered if labels[k]["true_verdict"] == "NOT_ELIGIBLE"
              and base[k]["verdict"] == "ELIGIBLE"
              and is_verbatim_quote(labels[k]["disqualifying_sentence"],
                                    labels[k]["source_text"])]
    rejects = [k for k in ordered if labels[k]["true_verdict"] == "NOT_ELIGIBLE"
               and tuned[k]["verdict"] == "NOT_ELIGIBLE"
               and normalize_ws(labels[k]["disqualifying_sentence"]) in
               {normalize_ws(q) for q in tuned[k].get("disqualifying_quotes", [])}
               and is_verbatim_quote(labels[k]["disqualifying_sentence"],
                                     labels[k]["source_text"])]
    failures = [k for k in ordered if tuned[k]["verdict"] != labels[k]["true_verdict"]]
    checks = [k for k in ordered if tuned[k]["verdict"] == "CHECK"]
    categories = [("baseline_missed_restriction", misses),
                  ("fine_tuned_correct_reject", rejects),
                  ("fine_tuned_failure_or_CHECK", failures or checks)]
    examples, used = [], set()
    for category, candidates in categories:
        if not candidates:
            raise ValueError(f"no actual example available for {category}")
        key = next((k for k in candidates if k not in used), candidates[0])
        used.add(key)
        examples.append({"category": category, "opportunity_id": key[0],
                         "profile_id": key[1], "candidate_count": len(candidates),
                         "label": labels[key],
                         "is_fine_tuned_error": tuned[key]["verdict"] != labels[key]["true_verdict"],
                         "predictions": {name: rows[key] for name, rows in systems.items()}})
    return examples


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
                    encoding="utf-8")


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def bundle_files(root):
    files = {}
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ValueError(f"symlink in bundle: {path}")
        relative = path.relative_to(root)
        # Python may create bytecode when the portable verifier is executed.
        if (relative.parts[:2] == ("src", "__pycache__") and
                path.is_file() and path.suffix == ".pyc"):
            continue
        if path.is_file() and relative.as_posix() != "provenance.json":
            files[relative.as_posix()] = {"sha256": digest(path), "bytes": path.stat().st_size}
    return files


def markdown(metrics, examples, notices, profiles, baseline, fine_tuned):
    lines = ["# Offline benchmark evidence", "",
             f"This bundle contains **{notices} notices x {profiles} constructed profiles "
             f"= {notices * profiles} labelled pairs**. The public benchmark is "
             "25 notices x 5 profiles = 125 pairs; synthetic fixtures may be smaller.", "",
             "## Interpretation and limits", "",
             "- Labels are single-author judgements under the included rubric; "
             "there is no independent inter-annotator agreement estimate.",
             "- These artifacts have seen diagnostic/development reuse. Treat results as "
             "a small development benchmark, not an untouched independent holdout or a "
             "causal estimate of fine-tuning benefit.",
             "- Pairs share notices and profiles: the effective notice-level sample is "
             f"{notices}, not {notices * profiles} independent observations.",
             "- Verification recomputes canonical metrics with bundled src.eval. "
             "Inference is NOT rerun; no training, provider calls, or keys are needed. "
             "Recorded latency is historical, not measured by verification.",
             "- Source text is copied only from the public labels CSV (also deduplicated "
             "in data/source_text.json). No raw API/contact payloads, logs, environment "
             "files, private configuration, or provider/checkpoint metadata are bundled.",
             "- Cost is null: eval_config.json is an intentionally empty, public metric "
             "configuration; no provider prices or local config are assumed.",
             "- Confirm in the original notice; this is a screening aid.", "",
             "## Fresh canonical metrics", "",
             "| System | Accuracy | Missed eligible grants | Human CHECK | Disqualified -> eligible |",
             "|---|---:|---:|---:|---:|"]
    for name, result in metrics["systems"].items():
        counts = [f"{result[m]['k']}/{result[m]['n']}" for m in
                  ("accuracy", "missed_grant_rate", "human_read_share",
                   "disqualified_to_eligible_error")]
        lines.append(f"| {name} | " + " | ".join(counts) + " |")
    lines += ["", "See eval.json for all metrics and eval_report.html for definitions.", "",
              "## Three worked examples", "",
              "Selection is deterministic: sort (opportunity_id, profile_id) lexically, "
              "take the first qualifying pair not already used (reuse only if necessary). "
              "The restriction miss requires truth NOT_ELIGIBLE and baseline ELIGIBLE. "
              "The correct reject also requires an exact whitespace-normalised, "
              "source-valid label quote. The final category prefers any fine-tuned "
              "label disagreement; only if none exists does it use a CHECK. "
              "These are illustrative categories, not a representative random sample. "
              "Full rows and public source text are in examples.json."]
    for example in examples:
        predictions = example["predictions"]
        lines += ["", f"### {example['category']}: {example['opportunity_id']} / {example['profile_id']}",
                  f"- Qualifying candidates: {example['candidate_count']}.",
                  f"- Label: **{example['label']['true_verdict']}**; "
                  f"{baseline}: **{predictions[baseline]['verdict']}**; "
                  f"{fine_tuned}: **{predictions[fine_tuned]['verdict']}**.",
                  f"- Label restriction: {example['label']['disqualifying_sentence'] or '(none labelled)' }",
                  "- Fine-tuned disqualifier quotes: " + json.dumps(
                      predictions[fine_tuned].get("disqualifying_quotes", []), ensure_ascii=False),
                  "- Fine-tuned CHECK quotes: " + json.dumps(
                      predictions[fine_tuned].get("check_quotes", []), ensure_ascii=False),
                  f"- Fine-tuned disagreement with label: {example['is_fine_tuned_error']}."]
    lines += ["", "## Offline rerun", "",
              "From this bundle's root, using Python 3.10+:", "", "```text", RERUN, "```", "",
              "The verifier uses the standard library, validates hashes and exact pair "
              "coverage, and compares freshly recomputed metrics and examples with the "
              "stored outputs. Bundled code contains only the evaluator, quote helpers, "
              "data models, and this CLI. No installation is needed for verification.", "",
              "Optional canonical evaluator CLI (requires the project's PyYAML dependency):", "",
              "```text", EVAL_RERUN, "```", "",
              "The optional command writes eval.rerun.*; remove those extra files before "
              "strict bundle verification. provenance.json records SHA256 and byte size "
              "for every payload file, including executable source. The manifest excludes "
              "itself (a file cannot contain its own SHA256); these hashes establish "
              "internal consistency, not an external authenticity signature.", ""]
    return "\n".join(lines)


def build_bundle(labels_path, profiles_dir, predictions_dir, sample_path, rubric,
                 output, baseline="code_only", fine_tuned="fine_tuned"):
    inputs = [Path(p) for p in (labels_path, profiles_dir, predictions_dir, sample_path, rubric)]
    labels, profiles, systems, _ = validate_inputs(*inputs)
    worked_examples(labels, systems, baseline, fine_tuned)
    output = Path(output)
    if output.exists():
        raise ValueError(f"output already exists; choose a new empty destination: {output}")
    # No directory traversal/copytree of the working checkout or prediction sidecars.
    output.mkdir(parents=True)
    for directory in ("data/profiles", "predictions", "src"):
        (output / directory).mkdir(parents=True, exist_ok=True)
    copies = {"data/labels.csv": inputs[0], "data/test_sample.csv": inputs[3],
              "data/rubric.md": inputs[4]}
    copies.update({f"data/profiles/{pid}.json": path for pid, path in profiles.items()})
    copies.update({f"predictions/{name}.jsonl": inputs[2] / f"{name}.jsonl" for name in systems})
    for target, source in copies.items():
        (output / target).write_bytes(public_bytes(source))
    for name in CODE_FILES:
        shutil.copyfile(Path(__file__).parent / name, output / "src" / name)
    labels, profiles, systems, sources = validate_inputs(
        output / "data/labels.csv", output / "data/profiles", output / "predictions",
        output / "data/test_sample.csv", output / "data/rubric.md")
    metrics = evaluator.run_evaluation(output / "data/labels.csv", output / "predictions", {})
    examples = worked_examples(labels, systems, baseline, fine_tuned)
    write_json(output / "eval_config.json", {})
    write_json(output / "eval.json", metrics)
    write_json(output / "examples.json", examples)
    write_json(output / "data/source_text.json", sources)
    (output / "eval_report.html").write_text(evaluator.render_report(metrics), encoding="utf-8")
    (output / "EVIDENCE.md").write_text(
        markdown(metrics, examples, len(sources), len(profiles), baseline, fine_tuned), encoding="utf-8")
    write_json(output / "provenance.json", {
        "schema_version": 1, "baseline": baseline, "fine_tuned": fine_tuned,
        "notices": len(sources), "profiles": len(profiles), "pairs": len(labels),
        "inference_rerun": False, "metric_implementation": "src.eval.run_evaluation",
        "metric_config": {}, "rerun_cwd": "bundle root", "rerun_command": RERUN,
        "canonical_eval_command": EVAL_RERUN,
        "input_copies": {target: {"source_name": source.name, "sha256": digest(output / target)}
                         for target, source in copies.items()},
        "metadata_policy": "Provider/checkpoint metadata omitted; no secrets or private config read.",
        "hash_scope": "Every payload file except provenance.json itself; runtime __pycache__ ignored.",
        "files": bundle_files(output),
    })
    verify_bundle(output)
    return metrics


def verify_bundle(root):
    root = Path(root)
    manifest = json.loads((root / "provenance.json").read_text(encoding="utf-8"))
    if manifest.get("schema_version") != 1 or manifest["files"] != bundle_files(root):
        raise ValueError("bundle SHA256/file inventory mismatch")
    if (manifest["inference_rerun"] is not False or manifest["metric_config"] != {} or
            manifest["rerun_command"] != RERUN or
            manifest["canonical_eval_command"] != EVAL_RERUN):
        raise ValueError("provenance rerun policy mismatch")
    for target, entry in manifest["input_copies"].items():
        if target not in manifest["files"] or entry["sha256"] != manifest["files"][target]["sha256"]:
            raise ValueError(f"input provenance hash mismatch: {target}")
    labels, profiles, systems, sources = validate_inputs(
        root / "data/labels.csv", root / "data/profiles", root / "predictions",
        root / "data/test_sample.csv", root / "data/rubric.md")
    metrics = evaluator.run_evaluation(root / "data/labels.csv", root / "predictions", {})
    examples = worked_examples(labels, systems, manifest["baseline"], manifest["fine_tuned"])
    expected = {"eval.json": metrics, "examples.json": examples,
                "data/source_text.json": sources, "eval_config.json": {}}
    for name, value in expected.items():
        if json.loads((root / name).read_text(encoding="utf-8")) != value:
            raise ValueError(f"recomputed content mismatch: {name}")
    if (manifest["notices"], manifest["profiles"], manifest["pairs"]) != (
            len(sources), len(profiles), len(labels)):
        raise ValueError("provenance benchmark dimensions mismatch")
    for name, text in {"eval_report.html": evaluator.render_report(metrics),
                       "EVIDENCE.md": markdown(metrics, examples, len(sources), len(profiles),
                                               manifest["baseline"], manifest["fine_tuned"])}.items():
        if (root / name).read_text(encoding="utf-8") != text:
            raise ValueError(f"recomputed content mismatch: {name}")
    return metrics


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build", help="copy public inputs and freshly evaluate; never infer")
    for flag, default in (("labels", "data/labels/test_labels.csv"),
                          ("profiles-dir", "data/profiles"),
                          ("predictions-dir", "results/predictions"),
                          ("sample", "data/samples/test_sample.csv"),
                          ("rubric", "data/labels/rubric.md"), ("output", "results/evidence")):
        build.add_argument("--" + flag, type=Path, default=Path(default))
    build.add_argument("--baseline", default="code_only")
    build.add_argument("--fine-tuned", default="fine_tuned")
    verify = sub.add_parser("verify", help="check hashes, coverage, metrics and examples offline")
    verify.add_argument("--bundle", type=Path, default=Path("results/evidence"))
    args = parser.parse_args(argv)
    try:
        if args.command == "build":
            metrics = build_bundle(args.labels, args.profiles_dir, args.predictions_dir,
                                   args.sample, args.rubric, args.output, args.baseline, args.fine_tuned)
            print(f"Wrote and verified {args.output}")
        else:
            metrics = verify_bundle(args.bundle)
            print(f"Verified {args.bundle}; inference was not rerun")
        for name, result in metrics["systems"].items():
            accuracy = result["accuracy"]
            print(f"{name}: accuracy {accuracy['k']}/{accuracy['n']}")
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
