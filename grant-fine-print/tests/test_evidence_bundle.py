"""Offline evidence behavior; every fixture/output lives under tmp_path."""

import csv
import json
import os
import shutil
import subprocess
import sys

import pytest

from src import eval as evaluator
from src.evidence_bundle import build_bundle, bundle_files, main, verify_bundle, write_json


@pytest.fixture
def artifacts(tmp_path):
    source = tmp_path / "public"
    source.mkdir()
    profiles = source / "profiles"
    predictions = source / "predictions"
    profiles.mkdir()
    predictions.mkdir()
    write_json(profiles / "p.json", {"id": "p", "name": "Constructed for-profit", "org_type": "forprofit"})
    labels = source / "labels.csv"
    sentence = "Only nonprofits may apply."
    with labels.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=["opportunity_id", "profile_id", "true_verdict",
                                                   "disqualifying_sentence", "source_text"])
        writer.writeheader()
        for oid, truth in (("a", "NOT_ELIGIBLE"), ("b", "NOT_ELIGIBLE"), ("c", "ELIGIBLE")):
            writer.writerow({"opportunity_id": oid, "profile_id": "p", "true_verdict": truth,
                             "disqualifying_sentence": sentence if truth == "NOT_ELIGIBLE" else "",
                             "source_text": sentence if truth == "NOT_ELIGIBLE" else "Open to all."})
    with (source / "sample.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerows([["opportunity_id"], ["a"], ["b"], ["c"]])
    (source / "rubric.md").write_text("# Single-author synthetic rubric\n", encoding="utf-8")
    for name, verdicts in (("code_only", ["ELIGIBLE"] * 3),
                           ("fine_tuned", ["CHECK", "NOT_ELIGIBLE", "CHECK"])):
        rows = [{"opportunity_id": oid, "profile_id": "p", "verdict": verdict,
                 "disqualifying_quotes": [sentence] if verdict == "NOT_ELIGIBLE" else []}
                for oid, verdict in zip("abc", verdicts)]
        (predictions / f"{name}.jsonl").write_text(
            "".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    return source


def build(source, output):
    return build_bundle(source / "labels.csv", source / "profiles", source / "predictions",
                        source / "sample.csv", source / "rubric.md", output)


def change_predictions(source, change):
    path = source / "predictions/fine_tuned.jsonl"
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    change(rows)
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")


def test_portable_bundle_recomputes_and_selects_real_examples(artifacts, tmp_path):
    # Adjacent private artifacts and sidecars must never enter the output.
    for name in (".env", "private_config.json", "raw_contacts.json", "run.log",
                 "predictions/fine_tuned.meta.json", "checkpoint.json"):
        (artifacts / name).write_text('api_key="synthetic-secret-not-public"', encoding="utf-8")
    output = tmp_path / "bundle"
    result = build(artifacts, output)
    assert result == evaluator.run_evaluation(artifacts / "labels.csv", artifacts / "predictions", {})
    assert result["systems"]["fine_tuned"]["accuracy"]["k"] == 1
    assert result["systems"]["code_only"]["disqualified_to_eligible_error"]["k"] == 2
    examples = json.loads((output / "examples.json").read_text(encoding="utf-8"))
    assert [(e["category"], e["opportunity_id"]) for e in examples] == [
        ("baseline_missed_restriction", "a"), ("fine_tuned_correct_reject", "b"),
        ("fine_tuned_failure_or_CHECK", "c")]
    assert examples[2]["is_fine_tuned_error"] is True
    assert examples[1]["predictions"]["fine_tuned"]["disqualifying_quotes"] == ["Only nonprofits may apply."]
    manifest = json.loads((output / "provenance.json").read_text(encoding="utf-8"))
    assert manifest["files"] == bundle_files(output)
    assert manifest["rerun_command"] == "python -m src.evidence_bundle verify --bundle ."
    assert manifest["inference_rerun"] is False
    assert not any(p.endswith((".log", ".meta.json")) or ".env" in p for p in manifest["files"])
    assert b"synthetic-secret-not-public" not in b"".join(p.read_bytes() for p in output.rglob("*") if p.is_file())
    for target, entry in manifest["input_copies"].items():
        assert manifest["files"][target]["sha256"] == entry["sha256"]
    relocated = tmp_path / "relocated with spaces"
    shutil.move(str(output), str(relocated))
    shutil.rmtree(artifacts)
    # -S proves verification works without site-packages (including PyYAML).
    process = subprocess.run([sys.executable, "-B", "-S", "-m", "src.evidence_bundle",
                              "verify", "--bundle", "."], cwd=relocated,
                             env={k: os.environ[k] for k in ("SystemRoot", "PATH") if k in os.environ},
                             capture_output=True, text=True, timeout=30)
    assert process.returncode == 0, process.stderr
    assert "inference was not rerun" in process.stdout


@pytest.mark.parametrize("mutation, error", [
    (lambda rows: rows.append(rows[0].copy()), "duplicate prediction"),
    (lambda rows: rows.pop(), "coverage mismatch"),
    (lambda rows: rows[0].update(opportunity_id="unknown"), "coverage mismatch"),
    (lambda rows: rows[0].update(verdict="MAYBE"), "invalid verdict"),
    (lambda rows: rows[0].update(contact_payload={"email": "private@example.test"}), "unknown fields"),
    (lambda rows: rows[0].update(override="Bearer abcdefghijklmnopqrstuvwxyz"), "credential"),
])
def test_reject_bad_predictions_before_creating_output(artifacts, tmp_path, mutation, error):
    change_predictions(artifacts, mutation)
    output = tmp_path / "bundle"
    with pytest.raises(ValueError, match=error):
        build(artifacts, output)
    assert not output.exists()


def test_duplicate_labels_fail(artifacts, tmp_path):
    path = artifacts / "labels.csv"
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    path.write_text("".join(lines + [lines[1]]), encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate label"):
        build(artifacts, tmp_path / "bundle")


def test_sample_mismatch_fails(artifacts, tmp_path):
    (artifacts / "sample.csv").write_text("opportunity_id\na\nb\n", encoding="utf-8")
    with pytest.raises(ValueError, match="test sample"):
        build(artifacts, tmp_path / "bundle")


def test_label_product_and_profile_coverage_fail(artifacts, tmp_path):
    path = artifacts / "labels.csv"
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    # A second profile only has one of three notices: not the full product.
    path.write_text("".join(lines + [lines[1].replace(",p,", ",p2,")]), encoding="utf-8")
    with pytest.raises(ValueError, match="Cartesian product"):
        build(artifacts, tmp_path / "bundle")
    path.write_text("".join(lines), encoding="utf-8")
    write_json(artifacts / "profiles/extra.json", {"id": "extra", "name": "Extra"})
    with pytest.raises(ValueError, match="profile JSON IDs"):
        build(artifacts, tmp_path / "bundle")


def test_check_example_is_not_claimed_as_failure_when_correct(artifacts, tmp_path):
    path = artifacts / "labels.csv"
    path.write_text(path.read_text(encoding="utf-8").replace("c,p,ELIGIBLE", "c,p,CHECK"), encoding="utf-8")
    change_predictions(artifacts, lambda rows: rows[0].update(
        verdict="NOT_ELIGIBLE", disqualifying_quotes=["Only nonprofits may apply."]))
    output = tmp_path / "bundle"
    build(artifacts, output)
    example = json.loads((output / "examples.json").read_text(encoding="utf-8"))[2]
    assert example["opportunity_id"] == "c"
    assert example["is_fine_tuned_error"] is False
    assert example["label"]["true_verdict"] == "CHECK"


def test_no_fabricated_example_when_category_absent(artifacts, tmp_path):
    path = artifacts / "predictions/code_only.jsonl"
    path.write_text(path.read_text(encoding="utf-8").replace("ELIGIBLE", "CHECK"), encoding="utf-8")
    with pytest.raises(ValueError, match="no actual example.*baseline"):
        build(artifacts, tmp_path / "bundle")


@pytest.mark.parametrize("tamper", ["payload", "extra", "metric_with_updated_hash"])
def test_verification_detects_corruption_and_recomputes(artifacts, tmp_path, tamper):
    output = tmp_path / "bundle"
    build(artifacts, output)
    if tamper == "payload":
        (output / "data/rubric.md").write_text("modified", encoding="utf-8")
    elif tamper == "extra":
        (output / "private.log").write_text("unlisted", encoding="utf-8")
    else:
        path = output / "eval.json"
        metrics = json.loads(path.read_text(encoding="utf-8"))
        metrics["systems"]["fine_tuned"]["accuracy"]["k"] = 99
        write_json(path, metrics)
        manifest_path = output / "provenance.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["files"] = bundle_files(output)
        write_json(manifest_path, manifest)
    with pytest.raises(ValueError, match="mismatch"):
        verify_bundle(output)


def test_cli_reports_failure_and_preserves_existing_output(artifacts, tmp_path, capsys):
    output = tmp_path / "bundle"
    build(artifacts, output)
    with pytest.raises(ValueError, match="already exists"):
        build(artifacts, output)
    assert main(["verify", "--bundle", str(tmp_path / "missing")]) == 1
    assert "error:" in capsys.readouterr().err
    assert verify_bundle(output)["systems"]["fine_tuned"]["n_pairs"] == 3


def test_bundle_accepts_current_serialized_verdict_rows(artifacts, tmp_path):
    from src.models import VerdictRow

    for path in (artifacts / "predictions").glob("*.jsonl"):
        rows = [VerdictRow.from_dict(json.loads(line))
                for line in path.read_text(encoding="utf-8").splitlines()]
        for row in rows:
            if row.verdict.value == "CHECK":
                row.check_reasons = ["Review the quoted rule against the profile."]
        path.write_text("".join(json.dumps(row.to_dict()) + "\n" for row in rows),
                        encoding="utf-8")
    build(artifacts, tmp_path / "bundle")
    assert verify_bundle(tmp_path / "bundle")["systems"]["fine_tuned"]["n_pairs"] == 3


def test_bundle_rejects_malformed_review_reasons(artifacts, tmp_path):
    change_predictions(artifacts, lambda rows: rows[0].update(check_reasons=[{"private": "payload"}]))
    with pytest.raises(ValueError, match="invalid check_reasons"):
        build(artifacts, tmp_path / "bundle")
