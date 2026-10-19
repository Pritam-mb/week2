"""Synthetic public inputs only: integrity, coverage, offline operation and preview."""

import csv
import json
import subprocess
import sys
from html.parser import HTMLParser
from pathlib import Path

import pytest

from src.evidence_bundle import bundle_files, digest, write_json
from src.matcher_replay import canonical_hash, run_replay, sha256
from src.models import Profile, text_hash
from src.proof_pack import (
    BANNER, STATUS_QUOTES, chosen_restriction, generate_pack, main, read_json, render_html,
    verify_pack,
)


MIXED_QUOTE = (
    "Organizations eligible to apply for this funding opportunity include U.S.-based "
    "and foreign non-profits, public international organizations, institutions of "
    "higher learning, and for-profit organizations."
)


def refresh(root):
    manifest = read_json(root / "provenance.json")
    manifest["files"] = bundle_files(root)
    write_json(root / "provenance.json", manifest)


@pytest.fixture
def inputs(tmp_path):
    bundle, replay = tmp_path / "evidence", tmp_path / "final"
    (bundle / "data/profiles").mkdir(parents=True)
    (bundle / "predictions").mkdir()
    profiles = {"p_nonus": {"id": "p_nonus", "name": "Foreign nonprofit",
                            "org_type": "nonprofit", "us_based": False},
                "p_forprofit": {"id": "p_forprofit", "name": "Domestic business",
                                "org_type": "for_profit", "us_based": True}}
    raw, sources = {}, {}
    for oid in ("359701", "360446", "360541"):
        foreign = "Foreign organizations" if oid != "360541" else "Foreign entities"
        quote = f"{foreign} are not eligible to apply."
        component = "Non-US components of US organizations are not eligible to apply."
        sources[oid] = f"{quote}\n{component}\nNotice {oid}."
        raw[oid] = [
            {"type": "citizenship_or_residency", "polarity": "excluded",
             "value": foreign, "quote": quote},
            {"type": "citizenship_or_residency", "polarity": "excluded",
             "value": "Non-US components", "quote": component}]
    sources["328026"] = (STATUS_QUOTES[0] + "\n" + MIXED_QUOTE + "\n" + STATUS_QUOTES[1] +
                         "\nUnrelated raw contact payload: DO-NOT-EXPORT@example.test")
    raw["328026"] = [{"type": "org_type", "polarity": "required",
                      "value": "U.S.-based and foreign non-profits, public international "
                               "organizations, institutions of higher learning, and for-profit organizations",
                      "quote": MIXED_QUOTE}]
    for pid, profile in profiles.items():
        write_json(bundle / f"data/profiles/{pid}.json", profile)
    with (bundle / "data/labels.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=["opportunity_id", "profile_id", "true_verdict",
                                                   "disqualifying_sentence", "source_text"])
        writer.writeheader()
        for oid, source in sources.items():
            for pid in profiles:
                rejected = oid != "328026" and pid == "p_nonus"
                writer.writerow({"opportunity_id": oid, "profile_id": pid,
                                 "true_verdict": "NOT_ELIGIBLE" if rejected else "CHECK",
                                 "disqualifying_sentence": raw[oid][0]["quote"] if rejected else "",
                                 "source_text": source})
    write_json(bundle / "data/source_text.json", sources)
    (bundle / "data/test_sample.csv").write_text(
        "opportunity_id\n" + "\n".join(sources) + "\n", encoding="utf-8")
    (bundle / "data/rubric.md").write_text("Synthetic labels only.\n", encoding="utf-8")
    for system in ("code_only", "prompted", "fine_tuned"):
        rows = []
        for oid in sources:
            for pid in profiles:
                verdict = ("CHECK" if oid == "328026" else "ELIGIBLE") if system == "code_only" else (
                    "ELIGIBLE" if (oid, pid) == ("328026", "p_forprofit") else "CHECK")
                rows.append({"opportunity_id": oid, "profile_id": pid, "verdict": verdict})
        (bundle / f"predictions/{system}.jsonl").write_text(
            "".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    write_json(bundle / "provenance.json", {"schema_version": 1, "notices": 4, "profiles": 2,
                                            "pairs": 8, "files": bundle_files(bundle)})
    snapshot = {"schema_version": 1, "evidence_provenance_sha256": digest(bundle / "provenance.json"),
                "sources": {text_hash(source): {"opportunity_id": oid,
                            "source_sha256": sha256(source.encode("utf-8")),
                            "systems": {name: {"conditions": raw[oid],
                                      "conditions_sha256": canonical_hash(raw[oid])}
                                        for name in ("prompted", "fine_tuned")}}
                            for oid, source in sources.items()}}
    snapshot_path = tmp_path / "snapshot.json"
    write_json(snapshot_path, snapshot)
    run_replay(bundle, replay, snapshot_path=snapshot_path)
    return bundle, replay


def build(inputs, output, **kwargs):
    return generate_pack(*inputs, output, **kwargs)


def test_roundtrip_all_candidates_honest_check_and_immutable_inputs(inputs, tmp_path):
    before = [(digest(root / "provenance.json"), bundle_files(root)) for root in inputs]
    output = tmp_path / "proof"
    proof = build(inputs, output)
    assert verify_pack(output) == proof
    assert proof["candidate_count"] == 3
    assert [(r["opportunity_id"], r["profile_id"]) for r in proof["candidates"]] == [
        ("359701", "p_nonus"), ("360446", "p_nonus"), ("360541", "p_nonus")]
    assert proof["candidate_profile_count"] == proof["candidate_rule_family_count"] == 1
    assert [r["opportunity_id"] for r in proof["examples"]] == ["360446", "359701", "328026"]
    assert proof["summary"]["replay_fine_tuned"] == {
        "pairs": 8, "automatic": 3, "check": 5,
        "automatic_label_agreement": {"k": 3, "n": 3, "rate": 1.0}}
    assert proof["summary"]["code_only"]["automatic"] == 6
    for candidate in proof["candidates"]:
        chosen = candidate["chosen_restriction"]
        assert chosen["interpretation"] == "conflict"
        assert chosen["membership"]["in_quoted_group"] is True
        assert chosen["opposite_geography_interpretation"] == "satisfied"
        assert candidate["source"]["full_source_semantically_adjudicated_by_software"] is False
    honest = proof["examples"][2]
    assert honest["label"]["true_verdict"] == "CHECK"
    assert honest["predictions"]["original_fine_tuned"]["verdict"] == "ELIGIBLE"
    assert honest["predictions"]["replay_fine_tuned"]["verdict"] == "CHECK"
    assert honest["extraction_review"]["raw_condition_count"] == 1
    assert honest["extraction_review"]["condition_interpretations"] == [None]
    assert honest["extraction_review"]["omitted_application_status_quotes"] == list(STATUS_QUOTES)
    assert honest["why_check"] == [
        "The source quote lists multiple organization types; review how the listed applicants are grouped."]
    payload = "\n".join(p.read_text(encoding="utf-8") for p in output.iterdir())
    assert "DO-NOT-EXPORT@example.test" not in payload
    assert BANNER in (output / "index.html").read_text(encoding="utf-8")
    assert before == [(digest(root / "provenance.json"), bundle_files(root)) for root in inputs]
    manifest = read_json(output / "provenance.json")
    assert manifest["inputs_unchanged_verified"] is True
    assert manifest["code_sha256"]["src/proof_pack.py"] == digest(
        Path(__file__).resolve().parents[1] / "src/proof_pack.py")
    assert "--replay " in proof["generation_command"]
    second = build(inputs, tmp_path / "second", second_id="360541")
    assert second["examples"][1]["opportunity_id"] == "360541"


@pytest.mark.parametrize("index, relative", [
    (0, "data/rubric.md"), (0, "predictions/prompted.jsonl"),
    (1, "REPLAY.md"), (1, "conditions_snapshot.json"),
])
def test_every_input_manifest_payload_is_checked(inputs, tmp_path, index, relative):
    path = inputs[index] / relative
    path.write_bytes(path.read_bytes() + b"\nTAMPER")
    output = tmp_path / "proof"
    with pytest.raises(ValueError, match="manifest payload SHA256"):
        build(inputs, output)
    assert not output.exists()


@pytest.mark.parametrize("index, relative, duplicate", [
    (0, "predictions/code_only.jsonl", False),
    (0, "predictions/fine_tuned.jsonl", True),
    (1, "predictions/replay_fine_tuned.jsonl", False),
    (1, "predictions/replay_prompted.jsonl", True),
])
def test_exact_pair_coverage_even_with_refreshed_manifest(inputs, tmp_path, index, relative, duplicate):
    root = inputs[index]
    path = root / relative
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    path.write_text("".join(lines + [lines[0]] if duplicate else lines[:-1]), encoding="utf-8")
    refresh(root)
    with pytest.raises(ValueError, match="duplicate prediction|prediction coverage mismatch"):
        build(inputs, tmp_path / "proof")
    assert not (tmp_path / "proof").exists()


def test_missing_label_cartesian_coverage(inputs, tmp_path):
    path = inputs[0] / "data/labels.csv"
    with path.open(encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        fields, rows = reader.fieldnames, list(reader)
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows[:-1])
    refresh(inputs[0])
    with pytest.raises(ValueError, match="Cartesian product"):
        build(inputs, tmp_path / "proof")


@pytest.mark.parametrize("field", ["source_sha256", "conditions_sha256"])
def test_nested_snapshot_hashes_cannot_hide_behind_refreshed_manifest(inputs, tmp_path, field):
    path = inputs[1] / "conditions_snapshot.json"
    snapshot = read_json(path)
    record = next(iter(snapshot["sources"].values()))
    target = record if field == "source_sha256" else record["systems"]["fine_tuned"]
    target[field] = "0" * 64
    write_json(path, snapshot)
    refresh(inputs[1])
    with pytest.raises(ValueError, match="source hash|conditions hash"):
        build(inputs, tmp_path / "proof")


@pytest.mark.parametrize("field, error", [
    ("evidence_provenance_sha256", "evidence provenance hash"),
    ("inputs_sha256", "input payload hashes"),
    ("snapshot_input_sha256", "snapshot input hash"),
    ("sources", "source/condition hashes"),
    ("code_sha256", "code hashes"),
])
def test_manifest_cross_links_and_code_hashes_are_checked(inputs, tmp_path, field, error):
    path = inputs[1] / "provenance.json"
    manifest = read_json(path)
    manifest[field] = {} if isinstance(manifest[field], dict) else "0" * 64
    write_json(path, manifest)
    with pytest.raises(ValueError, match=error):
        build(inputs, tmp_path / "proof")
    assert not (tmp_path / "proof").exists()


@pytest.mark.parametrize("change", ["invented_quote", "wrong_polarity", "wrong_profile"])
def test_chosen_restriction_requires_actual_quote_and_interpreter_conflict(change):
    quote = "Foreign organizations are not eligible to apply."
    row = {"disqualifying_quotes": [quote], "conditions": [{"type": "location",
           "polarity": "excluded", "value": "foreign", "quote": quote}]}
    profile = Profile(id="foreign", name="Foreign", org_type="nonprofit", us_based=False)
    if change == "invented_quote":
        row["disqualifying_quotes"] = ["Foreign organizations are excluded."]
    elif change == "wrong_polarity":
        row["conditions"][0]["polarity"] = "required"
    else:
        profile.us_based = True
    with pytest.raises(ValueError, match="not present in full source|no source-verified interpreter conflict"):
        chosen_restriction(row, profile, quote)


def test_refuses_existing_output_and_input_nesting(inputs, tmp_path):
    output = tmp_path / "proof"
    output.mkdir()
    sentinel = output / "user-work.txt"
    sentinel.write_text("preserve", encoding="utf-8")
    with pytest.raises(ValueError, match="output already exists"):
        build(inputs, output)
    assert sentinel.read_text(encoding="utf-8") == "preserve"
    for root in inputs:
        with pytest.raises(ValueError, match="separate from both input"):
            build(inputs, root / "nested-proof")


def test_hero_and_second_must_be_qualifying_pairs(inputs, tmp_path):
    assert main(["--bundle", str(inputs[0]), "--replay", str(inputs[1]),
                 "--output", str(tmp_path / "proof"), "--hero-id", "328026"]) == 1
    assert not (tmp_path / "proof").exists()
    with pytest.raises(ValueError, match="another qualifying catch"):
        build(inputs, tmp_path / "proof", second_id="360446")


def test_output_tamper_is_detected(inputs, tmp_path):
    output = tmp_path / "proof"
    build(inputs, output)
    path = output / "index.html"
    path.write_text(path.read_text(encoding="utf-8") + "tamper", encoding="utf-8")
    with pytest.raises(ValueError, match="manifest payload SHA256"):
        verify_pack(output)


class ParsedHTML(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tags, self.attributes, self.text = [], [], []

    def handle_starttag(self, tag, attrs):
        self.tags.append(tag)
        self.attributes.extend(attrs)

    def handle_data(self, data):
        self.text.append(data)


def test_html_escapes_every_dynamic_comparison_and_has_no_external_dependencies(inputs, tmp_path):
    proof = build(inputs, tmp_path / "proof")
    attack = '</pre><script>alert("x")</script><img src="https://bad.test" onerror="boom"> & \' '
    for row in proof["examples"]:
        row["profile"]["name"] = attack
        row["label"]["disqualifying_sentence"] = attack
        row["source"]["path"] = attack
        row["predictions"]["replay_fine_tuned"]["conditions"][0]["value"] = attack
        if "chosen_restriction" in row:
            row["chosen_restriction"]["condition"]["quote"] = attack
        else:
            row["why_check"] = [attack]
            row["extraction_review"]["omitted_application_status_quotes"] = [attack]
    rendered = render_html(proof)
    parsed = ParsedHTML()
    parsed.feed(rendered)
    assert "script" not in parsed.tags and "img" not in parsed.tags
    assert "iframe" not in parsed.tags and "link" not in parsed.tags
    assert not any(name.startswith("on") or name == "src" for name, _ in parsed.attributes)
    assert not any(value and value.startswith(("http:", "https:", "//"))
                   for _, value in parsed.attributes)
    assert "&lt;script&gt;" in rendered and "&amp;" in rendered
    assert attack in "".join(parsed.text)
    assert "Why CHECK" in "".join(parsed.text)


def test_generation_imports_no_inference_runtime_and_reads_no_environment_or_config(inputs, tmp_path):
    script = r'''
import builtins, pathlib, sys
blocked = ("src.extract", "src.pipeline", "src.config", "src.adapters", "src.pull",
           "src.cli", "src.train", "dotenv", "requests", "openai", "tinker")
original_import = builtins.__import__
def guarded_import(name, *args, **kwargs):
    if any(name == prefix or name.startswith(prefix + ".") for prefix in blocked):
        raise AssertionError("runtime import: " + name)
    return original_import(name, *args, **kwargs)
builtins.__import__ = guarded_import
def audit(event, args):
    if event == "open" and isinstance(args[0], (str, bytes)):
        name = pathlib.Path(args[0]).name.lower()
        if name.startswith(".env") or name in {"config.yaml", "config.yml", "config.json"}:
            raise AssertionError("private/config file read: " + name)
    if event in {"socket.connect", "socket.getaddrinfo"}:
        raise AssertionError("network operation")
sys.addaudithook(audit)
from src import proof_pack
def forbidden(*args, **kwargs):
    raise AssertionError("config loader called")
proof_pack.evaluator.load_config = forbidden
assert proof_pack.main(sys.argv[1:]) == 0
assert not any(name == p or name.startswith(p + ".") for name in sys.modules for p in blocked)
'''
    output = tmp_path / "offline-proof"
    result = subprocess.run([sys.executable, "-B", "-c", script, "--bundle", str(inputs[0]),
                             "--replay", str(inputs[1]), "--output", str(output)],
                            cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    assert verify_pack(output)["candidate_count"] == 3
