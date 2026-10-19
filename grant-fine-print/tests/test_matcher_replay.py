"""Synthetic offline replay, strict coverage, reproducibility and export privacy."""

import csv
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from src import eval as evaluator
from src.evidence_bundle import bundle_files, digest, write_json
from src.matcher_replay import (
    BACKENDS, canonical_hash, main, read_json, run_replay, text_hash,
)


def condition(**changes):
    row = {"type": "org_type", "polarity": "required", "value": "nonprofit",
           "quote": "Only nonprofits may apply."}
    return {**row, **changes}


def refresh_manifest(bundle):
    write_json(bundle / "provenance.json", {
        "schema_version": 1, "notices": 2, "profiles": 2, "pairs": 4,
        "files": bundle_files(bundle),
    })


@pytest.fixture
def inputs(tmp_path):
    bundle, cache = tmp_path / "evidence", tmp_path / "cache"
    (bundle / "data/profiles").mkdir(parents=True)
    (bundle / "predictions").mkdir()
    sources = {"a": "Only nonprofits may apply.\n\nDomestic organizations are welcome.",
               "b": "Consult the original notice for details."}
    for pid, org in (("business", "for_profit"), ("nonprofit", "nonprofit")):
        write_json(bundle / f"data/profiles/{pid}.json",
                   {"id": pid, "name": pid, "org_type": org, "us_based": True})
    with (bundle / "data/labels.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=["opportunity_id", "profile_id",
                                "true_verdict", "disqualifying_sentence", "source_text"])
        writer.writeheader()
        for oid, source in sources.items():
            for pid in ("business", "nonprofit"):
                rejected = oid == "a" and pid == "business"
                writer.writerow({"opportunity_id": oid, "profile_id": pid,
                                 "true_verdict": "NOT_ELIGIBLE" if rejected else "CHECK",
                                 "disqualifying_sentence": condition()["quote"] if rejected else "",
                                 "source_text": source})
    (bundle / "data/test_sample.csv").write_text("opportunity_id\na\nb\n", encoding="utf-8")
    (bundle / "data/rubric.md").write_text("Synthetic single-author labels.\n", encoding="utf-8")
    for system in ("code_only", *BACKENDS):
        rows = [{"opportunity_id": oid, "profile_id": pid, "verdict": "ELIGIBLE",
                 "latency_ms": 123.0} for oid in sources for pid in ("business", "nonprofit")]
        (bundle / f"predictions/{system}.jsonl").write_text(
            "".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    refresh_manifest(bundle)
    for backend in BACKENDS.values():
        (cache / backend).mkdir(parents=True)
        for oid, source in sources.items():
            key = text_hash(source)
            raw = [condition(), condition(type="location", value="non-US",
                                          quote="Only foreign organizations may apply.")]
            write_json(cache / backend / f"{key[:12]}.json", {
                "hash": key, "cache_key": key[:12], "backend": backend,
                "opportunity_id": oid, "conditions": raw if oid == "a" else [],
            })
    return bundle, cache, sources


def cache_path(inputs):
    _, cache, sources = inputs
    return cache / BACKENDS["prompted"] / f"{text_hash(sources['a'])[:12]}.json"


def run(inputs, output):
    bundle, cache, _ = inputs
    return run_replay(bundle, output, legacy_cache=cache)


def test_roundtrip_replays_verified_and_dropped_quotes_without_cache(inputs, tmp_path):
    bundle, cache, sources = inputs
    original_files = bundle_files(bundle)
    original_provenance = digest(bundle / "provenance.json")
    first = tmp_path / "initial"
    metrics = run(inputs, first)
    assert metrics == evaluator.run_evaluation(bundle / "data/labels.csv", first / "predictions", {})
    rows = evaluator.load_predictions(first / "predictions/replay_prompted.jsonl")
    keyed = {(row["opportunity_id"], row["profile_id"]): row for row in rows}
    rejection = keyed["a", "business"]
    assert rejection["verdict"] == "NOT_ELIGIBLE"
    assert rejection["disqualifying_quotes"] == [condition()["quote"]]
    assert rejection["proposed_disqualifier_quotes"] == [
        condition()["quote"], "Only foreign organizations may apply."]
    assert keyed["a", "nonprofit"]["verdict"] == "CHECK"  # dropped quote forces abstention
    assert keyed["a", "nonprofit"]["check_quotes"] == []
    assert keyed["a", "nonprofit"]["check_reasons"]
    assert keyed["b", "business"]["verdict"] == "CHECK"  # explicit empty cache is valid
    assert all(row["latency_ms"] is None and row["override"] is None for row in rows)
    assert metrics["systems"]["replay_prompted"]["quote_validity"] == {
        "k": 1, "n": 3, "rate": 1 / 3}
    assert metrics["systems"]["replay_prompted"]["accuracy"]["k"] == 4
    for name in ("code_only", "prompted", "fine_tuned"):
        target = name if name == "code_only" else f"original_{name}"
        assert (first / f"predictions/{target}.jsonl").read_bytes() == (
            bundle / f"predictions/{name}.jsonl").read_bytes()
    manifest = read_json(first / "provenance.json")
    assert manifest["evidence_provenance_sha256"] == original_provenance
    assert manifest["snapshot_roundtrip_verified"] is True
    assert manifest["files"] == bundle_files(first)
    assert manifest["verifier_dropped_conditions"]["prompted"] == {"a": 1, "b": 0}
    for name in ("match", "models", "verify"):
        assert manifest["code_sha256"][f"src/{name}.py"] == digest(
            Path(__file__).resolve().parents[1] / f"src/{name}.py")
    snapshot = read_json(first / "conditions_snapshot.json")
    for oid, source in sources.items():
        record = snapshot["sources"][text_hash(source)]
        assert record["opportunity_id"] == oid
        for entry in record["systems"].values():
            assert entry["conditions_sha256"] == canonical_hash(entry["conditions"])
    shutil.rmtree(cache)
    second = tmp_path / "snapshot-only"
    assert run_replay(bundle, second, snapshot_path=first / "conditions_snapshot.json") == metrics
    for relative in bundle_files(first):
        assert (first / relative).read_bytes() == (second / relative).read_bytes()
    assert read_json(second / "provenance.json")["mode"] == "snapshot"
    assert bundle_files(bundle) == original_files
    assert digest(bundle / "provenance.json") == original_provenance


def test_export_allowlist_excludes_provider_secrets_and_private_sidecars(inputs, tmp_path):
    _, cache, _ = inputs
    path = cache_path(inputs)
    data = read_json(path)
    data.update(api_key="synthetic-secret-not-public", provider_url="https://private.test",
                checkpoint={"token": "synthetic-secret-not-public"})
    data["conditions"][0]["api_key"] = "synthetic-secret-not-public"
    write_json(path, data)
    for name in (".env", "raw_contacts.json", "private.log", "provider.meta.json"):
        (cache / name).write_text("synthetic-secret-not-public", encoding="utf-8")
    # An unrelated malformed cache file must not be opened or exported.
    (cache / BACKENDS["prompted"] / "unrelated.json").write_text("not JSON", encoding="utf-8")
    output = tmp_path / "replay"
    run(inputs, output)
    payload = b"".join(path.read_bytes() for path in output.rglob("*") if path.is_file())
    assert b"synthetic-secret-not-public" not in payload
    assert b"private.test" not in payload
    assert b"checkpoint" not in (output / "conditions_snapshot.json").read_bytes()
    for record in read_json(output / "conditions_snapshot.json")["sources"].values():
        assert set(record) == {"opportunity_id", "source_sha256", "systems"}
        for entry in record["systems"].values():
            for row in entry["conditions"]:
                assert set(row) == {"type", "polarity", "value", "quote"}


@pytest.mark.parametrize("change, error", [
    (lambda data: data.update(hash=data["hash"][:12] + "0" * 52), "full source hash mismatch"),
    (lambda data: data.update(opportunity_id="wrong"), "opportunity_id mismatch"),
    (lambda data: data.update(backend="MockBackend"), "envelope mismatch"),
    (lambda data: data.update(conditions=None), "must be a list"),
    (lambda data: data.update(conditions={}), "must be a list"),
    (lambda data: data.pop("conditions"), "must be a list"),
    (lambda data: data["conditions"].append("invalid"), "required fields"),
    (lambda data: data["conditions"][0].pop("quote"), "required fields"),
    (lambda data: data["conditions"][0].update(value=7), "non-string"),
    (lambda data: data["conditions"][0].update(quote=None), "non-string"),
    (lambda data: data["conditions"][0].update(type="made_up"), "invalid condition enum"),
    (lambda data: data["conditions"][0].update(polarity="maybe"), "invalid condition enum"),
    (lambda data: data["conditions"][0].update(value="api_key=synthetic-secret-not-public"),
     "possible credential"),
])
def test_corrupt_legacy_cache_fails_before_output(inputs, tmp_path, change, error):
    path = cache_path(inputs)
    data = read_json(path)
    change(data)
    write_json(path, data)
    output = tmp_path / "replay"
    with pytest.raises(ValueError, match=error):
        run(inputs, output)
    assert not output.exists()


def test_missing_cache_is_not_an_empty_extraction(inputs, tmp_path):
    cache_path(inputs).unlink()
    output = tmp_path / "replay"
    with pytest.raises(ValueError, match="missing legacy cache"):
        run(inputs, output)
    assert not output.exists()


@pytest.mark.parametrize("tamper, error", [
    ("source_hash", "source hash/opportunity_id"),
    ("source_key", "source coverage"),
    ("missing_system", "system coverage"),
    ("conditions_hash", "conditions hash mismatch"),
    ("extra_field", "non-allowlisted"),
    ("provenance", "provenance hash mismatch"),
])
def test_snapshot_hash_identity_and_coverage_checks(inputs, tmp_path, tamper, error):
    first = tmp_path / "first"
    run(inputs, first)
    path = first / "conditions_snapshot.json"
    snapshot = read_json(path)
    key = text_hash(inputs[2]["a"])
    record = snapshot["sources"][key]
    entry = record["systems"]["prompted"]
    if tamper == "source_hash":
        record["source_sha256"] = "0" * 64
    elif tamper == "source_key":
        snapshot["sources"]["0" * 64] = snapshot["sources"].pop(key)
    elif tamper == "missing_system":
        record["systems"].pop("fine_tuned")
    elif tamper == "conditions_hash":
        entry["conditions"][0]["value"] = "university"
    elif tamper == "extra_field":
        entry["conditions"][0]["private"] = "no export"
    else:
        snapshot["evidence_provenance_sha256"] = "0" * 64
    write_json(path, snapshot)
    output = tmp_path / "second"
    with pytest.raises(ValueError, match=error):
        run_replay(inputs[0], output, snapshot_path=path)
    assert not output.exists()


@pytest.mark.parametrize("target, duplicate, error", [
    ("labels", True, "duplicate label"),
    ("labels", False, "Cartesian product"),
    ("predictions", True, "duplicate prediction"),
    ("predictions", False, "prediction coverage mismatch"),
    ("profiles", False, "profile JSON IDs"),
])
def test_duplicate_and_missing_coverage_fail(inputs, tmp_path, target, duplicate, error):
    bundle = inputs[0]
    if target == "labels":
        path = bundle / "data/labels.csv"
        with path.open(encoding="utf-8", newline="") as stream:
            reader = csv.DictReader(stream)
            fields = reader.fieldnames
            rows = list(reader)
        rows = rows + [rows[0]] if duplicate else rows[:-1]
        with path.open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)
    elif target == "predictions":
        path = bundle / "predictions/prompted.jsonl"
        lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
        path.write_text("".join(lines + [lines[0]] if duplicate else lines[:-1]), encoding="utf-8")
    else:
        (bundle / "data/profiles/business.json").unlink()
    # Update only the synthetic manifest so coverage validation is exercised.
    refresh_manifest(bundle)
    output = tmp_path / "replay"
    with pytest.raises(ValueError, match=error):
        run(inputs, output)
    assert not output.exists()


def test_duplicate_json_keys_fail(inputs, tmp_path):
    path = cache_path(inputs)
    data = path.read_text(encoding="utf-8")
    path.write_text(data.replace('"conditions":', '"conditions": [], "conditions":', 1),
                    encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate JSON key"):
        run(inputs, tmp_path / "replay")


def test_evidence_hash_mismatch_fails(inputs, tmp_path):
    (inputs[0] / "data/rubric.md").write_text("tampered", encoding="utf-8")
    with pytest.raises(ValueError, match="evidence SHA256/file inventory mismatch"):
        run(inputs, tmp_path / "replay")


def test_cli_snapshot_works_without_site_packages_or_inference_imports(inputs, tmp_path):
    output = tmp_path / "first"
    run(inputs, output)
    shutil.rmtree(inputs[1])
    project = Path(__file__).resolve().parents[1]
    # Refuse imports as well as calls: snapshot mode must stay wholly offline.
    script = """
import importlib.abc
import sys
class BlockRemote(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname in {'src.config', 'src.extract', 'src.pipeline', 'requests', 'dotenv'}:
            raise AssertionError('forbidden replay import: ' + fullname)
sys.meta_path.insert(0, BlockRemote())
from src import eval as evaluator
def forbidden(*args, **kwargs):
    raise AssertionError('config loader called')
evaluator.load_config = forbidden
from src.matcher_replay import main
sys.exit(main(sys.argv[1:]))
"""
    process = subprocess.run(
        [sys.executable, "-B", "-S", "-c", script, "--bundle", str(inputs[0]),
         "--snapshot", str(output / "conditions_snapshot.json"),
         "--output", str(tmp_path / "second")], cwd=project,
        capture_output=True, text=True, timeout=30)
    assert process.returncode == 0, process.stderr
    assert "no inference" in process.stdout
    assert read_json(output / "eval.json") == read_json(tmp_path / "second/eval.json")


def test_cli_reports_failure_and_preserves_existing_output(inputs, tmp_path, capsys):
    output = tmp_path / "first"
    run(inputs, output)
    before = bundle_files(output)
    assert main(["--bundle", str(inputs[0]), "--legacy-cache", str(inputs[1]),
                 "--output", str(output)]) == 1
    assert "already exists" in capsys.readouterr().err
    assert bundle_files(output) == before
    with pytest.raises(ValueError, match="exactly one"):
        run_replay(inputs[0], tmp_path / "invalid")
