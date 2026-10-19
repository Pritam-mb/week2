"""Synthetic evidence only: real manifest/replay validation, mutations and art."""

import copy
import csv
import json
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from src.evidence_bundle import bundle_files, digest, write_json
from src.matcher_replay import canonical_hash, run_replay, sha256
from src.models import text_hash
from src.proof_pack import STATUS_QUOTES, generate_pack, read_json
from src.submission_hero import (
    HEIGHT, NS, PNG_NAME, PROVENANCE_NAME, SVG_NAME, WIDTH, generate,
    input_hashes, main, render_png, render_svg, validated_proof,
)


QUOTE = "Non-domestic (non-U.S.) Entities (Foreign Organizations) are not eligible to apply."
MIXED = ("Organizations eligible to apply for this funding opportunity include U.S.-based "
         "and foreign non-profits, public international organizations, institutions of "
         "higher learning, and for-profit organizations.")


def refresh(root):
    manifest = read_json(root / "provenance.json")
    manifest["files"] = bundle_files(root)
    write_json(root / "provenance.json", manifest)


@pytest.fixture
def evidence(tmp_path):
    bundle, replay, pack = (tmp_path / name for name in ("evidence", "replay", "proof"))
    (bundle / "data/profiles").mkdir(parents=True)
    (bundle / "predictions").mkdir()
    profiles = {
        "p_nonus": {"id": "p_nonus", "name": "Synthetic UK Trust", "org_type": "nonprofit",
                    "us_based": False, "notes": "Constructed profile: United Kingdom nonprofit."},
        "p_forprofit": {"id": "p_forprofit", "name": "Synthetic business",
                        "org_type": "for_profit", "us_based": True},
    }
    sources = {oid: QUOTE + "\nNotice " + oid for oid in ("359701", "360446", "360541")}
    sources["328026"] = STATUS_QUOTES[0] + "\n" + MIXED
    raw = {oid: [{"type": "citizenship_or_residency", "polarity": "excluded",
                  "value": "Non-domestic (non-U.S.) Entities (Foreign Organizations)", "quote": QUOTE}]
           for oid in sources if oid != "328026"}
    raw["328026"] = [{"type": "org_type", "polarity": "required", "quote": MIXED,
                      "value": "U.S.-based and foreign non-profits, public international "
                               "organizations, institutions of higher learning, and for-profit organizations"}]
    for pid, profile in profiles.items():
        write_json(bundle / f"data/profiles/{pid}.json", profile)
    with (bundle / "data/labels.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=["opportunity_id", "profile_id", "true_verdict",
                                                   "disqualifying_sentence", "source_text"])
        writer.writeheader()
        for oid, source in sources.items():
            for pid in profiles:
                rejected = oid != "328026" and pid == "p_nonus"
                writer.writerow({"opportunity_id": oid, "profile_id": pid,
                                 "true_verdict": "NOT_ELIGIBLE" if rejected else "CHECK",
                                 "disqualifying_sentence": QUOTE if rejected else "", "source_text": source})
    write_json(bundle / "data/source_text.json", sources)
    (bundle / "data/test_sample.csv").write_text(
        "opportunity_id\n" + "\n".join(sources) + "\n", encoding="utf-8")
    (bundle / "data/rubric.md").write_text("Synthetic only.\n", encoding="utf-8")
    for system in ("code_only", "prompted", "fine_tuned"):
        rows = [{"opportunity_id": oid, "profile_id": pid,
                 "verdict": ("CHECK" if oid == "328026" else "ELIGIBLE") if system == "code_only"
                 else ("ELIGIBLE" if (oid, pid) == ("328026", "p_forprofit") else "CHECK")}
                for oid in sources for pid in profiles]
        (bundle / f"predictions/{system}.jsonl").write_text(
            "".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    write_json(bundle / "provenance.json", {"schema_version": 1, "notices": 4, "profiles": 2,
                                           "pairs": 8, "files": bundle_files(bundle)})
    snapshot = {"schema_version": 1, "evidence_provenance_sha256": digest(bundle / "provenance.json"),
                "sources": {text_hash(source): {"opportunity_id": oid,
                            "source_sha256": sha256(source.encode("utf-8")),
                            "systems": {system: {"conditions": raw[oid],
                                                "conditions_sha256": canonical_hash(raw[oid])}
                                        for system in ("prompted", "fine_tuned")}}
                            for oid, source in sources.items()}}
    snapshot_path = tmp_path / "snapshot.json"
    write_json(snapshot_path, snapshot)
    run_replay(bundle, replay, snapshot_path=snapshot_path)
    proof = generate_pack(bundle, replay, pack)
    return pack, bundle, replay, proof


def art_dir(tmp_path, proof):
    output = tmp_path / "images"
    output.mkdir()
    (output / SVG_NAME).write_text(render_svg(proof), encoding="utf-8")
    return output


def test_validated_generation_roundtrip_scope_and_unchanged_inputs(evidence, tmp_path):
    pack, bundle, replay, proof = evidence
    before = input_hashes(pack, bundle, replay)
    assert validated_proof(pack, bundle, replay)[0] == proof
    output = art_dir(tmp_path, proof)
    provenance = generate(pack, bundle, replay, output, renderer="none")
    assert read_json(output / PROVENANCE_NAME) == provenance
    assert provenance["input_sha256"] == before == input_hashes(pack, bundle, replay)
    assert provenance["dimensions"] == {"width": 1600, "height": 840}
    assert provenance["hero"]["exact_quote"] == QUOTE
    assert provenance["hero"]["baseline_display"] == "LIKELY ELIGIBLE"
    assert provenance["hero"]["replay_display"] == "NOT ELIGIBLE"
    assert "3 pairs / one rule family · 2/8 CHECK" in provenance["visible_scope"]
    assert provenance["inference_rerun"] is False
    assert all(provenance["verification"].values())
    assert "python -B -m src.submission_hero --pack" in provenance["generation_command"]
    assert provenance["renderer"]["png_created"] is False
    assert not (output / PNG_NAME).exists()
    for name, record in provenance["files"].items():
        assert record["sha256"] == digest(output / name)


@pytest.mark.parametrize("root_index, relative", [
    (0, "examples.json"), (0, "index.html"), (1, "data/rubric.md"),
    (1, "predictions/code_only.jsonl"), (2, "conditions_snapshot.json"),
    (2, "predictions/replay_fine_tuned.jsonl"),
])
def test_payload_tampering_fails_before_output(evidence, tmp_path, root_index, relative):
    roots = evidence[:3]
    path = roots[root_index] / relative
    path.write_bytes(path.read_bytes() + b"\nTAMPER")
    with pytest.raises(ValueError, match="manifest payload SHA256"):
        generate(*roots, tmp_path / "absent", renderer="none")
    assert not (tmp_path / "absent").exists()


@pytest.mark.parametrize("mutation", ["missing", "duplicate", "wrong_pair", "baseline", "replay",
                                     "profile", "unverified", "scope", "counts", "quote"])
def test_synthetic_semantic_mutations_are_rejected(evidence, mutation):
    proof = copy.deepcopy(evidence[3])
    hero = proof["examples"][0]
    if mutation == "missing":
        proof["examples"] = proof["examples"][1:]
    elif mutation == "duplicate":
        proof["examples"].append(copy.deepcopy(hero))
    elif mutation == "wrong_pair":
        hero["opportunity_id"] = "359701"
    elif mutation == "baseline":
        hero["predictions"]["code_only"]["verdict"] = "CHECK"
    elif mutation == "replay":
        hero["predictions"]["replay_fine_tuned"]["verdict"] = "ELIGIBLE"
    elif mutation == "profile":
        hero["profile"]["us_based"] = True
    elif mutation == "unverified":
        hero["chosen_restriction"]["quote_verified_against_full_source"] = False
    elif mutation == "scope":
        proof["candidate_rule_family_count"] = 2
    elif mutation == "counts":
        proof["summary"]["replay_fine_tuned"]["check"] += 1
    else:
        hero["chosen_restriction"]["condition"]["quote"] = "Invented restriction."
    with pytest.raises(ValueError):
        render_svg(proof)


def test_refreshed_pack_cannot_replace_revalidated_inputs(evidence):
    # A consistent manifest and all three public views still cannot invent a profile.
    from src.proof_pack import render_html, render_markdown
    pack, bundle, replay, proof = evidence
    proof["examples"][0]["profile"]["name"] = "Invented public profile"
    write_json(pack / "examples.json", proof)
    (pack / "index.html").write_text(render_html(proof), encoding="utf-8")
    (pack / "PROOF.md").write_text(render_markdown(proof), encoding="utf-8")
    refresh(pack)
    with pytest.raises(ValueError, match="differs from revalidated"):
        validated_proof(pack, bundle, replay)


def test_refreshed_replay_manifest_cannot_hide_nested_source_hash_tampering(evidence):
    pack, bundle, replay, _ = evidence
    path = replay / "conditions_snapshot.json"
    snapshot = read_json(path)
    next(iter(snapshot["sources"].values()))["source_sha256"] = "0" * 64
    write_json(path, snapshot)
    refresh(replay)
    with pytest.raises(ValueError, match="source hash"):
        validated_proof(pack, bundle, replay)


def test_svg_is_accessible_escaped_xml_without_external_assets(evidence):
    proof = copy.deepcopy(evidence[3])
    hero = proof["examples"][0]
    attack = '<script>& "UK"'
    hero["profile"]["name"] = attack
    hero["chosen_restriction"]["condition"]["quote"] = QUOTE + " <&>"
    hero["predictions"]["replay_fine_tuned"]["disqualifying_quotes"] = [QUOTE + " <&>"]
    svg = render_svg(proof)
    root = ET.fromstring(svg)
    assert (root.attrib["width"], root.attrib["height"]) == ("1600", "840")
    assert root.attrib["aria-labelledby"] == "title description"
    assert attack in "".join(root.itertext())
    assert "&lt;script&gt;" in svg and "&amp;" in svg and "&lt;&amp;&gt;" in svg
    assert {element.tag for element in root.iter()} <= {
        f"{{{NS}}}{tag}" for tag in ("svg", "title", "desc", "rect", "line", "text")}
    assert not any("href" in key or key.startswith("on")
                   for element in root.iter() for key in element.attrib)
    assert "Generated proof card, not a live application screenshot" in "".join(root.itertext())


def test_art_tampering_and_input_nesting_fail(evidence, tmp_path):
    pack, bundle, replay, proof = evidence
    output = art_dir(tmp_path, proof)
    (output / SVG_NAME).write_text("<svg/>", encoding="utf-8")
    with pytest.raises(ValueError, match="SVG differs"):
        generate(pack, bundle, replay, output, renderer="none")
    assert not (output / PROVENANCE_NAME).exists()
    for root in (pack, bundle, replay):
        with pytest.raises(ValueError, match="separate from"):
            generate(pack, bundle, replay, root / "nested", renderer="none")


def test_missing_renderer_is_honest_and_stale_png_not_blessed(evidence, tmp_path, monkeypatch):
    import builtins
    original_import = builtins.__import__

    def missing(name, *args, **kwargs):
        if name == "PIL" or name.startswith("PIL."):
            raise ImportError("synthetic missing renderer")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", missing)
    pack, bundle, replay, proof = evidence
    output = art_dir(tmp_path, proof)
    result = generate(pack, bundle, replay, output)
    assert result["renderer"]["png_created"] is False
    assert "not installed" in result["renderer"]["blocker"]
    (output / PNG_NAME).write_bytes(b"stale")
    with pytest.raises(ValueError, match="existing PNG"):
        generate(pack, bundle, replay, output)


def test_local_pillow_renders_actual_png_and_catches_overflow(evidence, tmp_path):
    Image = pytest.importorskip("PIL.Image")
    pack, bundle, replay, proof = evidence
    output = art_dir(tmp_path, proof)
    provenance = generate(pack, bundle, replay, output, renderer="pillow")
    with Image.open(output / PNG_NAME) as image:
        assert image.format == "PNG" and image.size == (WIDTH, HEIGHT)
        assert image.getpixel((0, 0)) == (234, 226, 208)
        assert image.getpixel((40, 40)) == (250, 246, 238)
        assert image.convert("L").getextrema()[0] < 50
    assert provenance["renderer"]["fonts_sha256"]
    assert provenance["files"][PNG_NAME]["sha256"] == digest(output / PNG_NAME)
    invalid = render_svg(proof).replace('x="900" y="279"', 'x="1590" y="279"')
    with pytest.raises(ValueError, match="measured text overflow"):
        render_png(invalid, tmp_path / "overflow.png", "pillow")
    assert not (tmp_path / "overflow.png").exists()


def test_offline_cli_no_private_config_or_inference_imports(evidence, tmp_path):
    pack, bundle, replay, proof = evidence
    output = art_dir(tmp_path, proof)
    script = r'''
import builtins, pathlib, sys
blocked = ("src.extract", "src.pipeline", "src.config", "src.adapters", "src.pull",
           "dotenv", "requests", "openai", "tinker")
original = builtins.__import__
def guarded(name, *args, **kwargs):
    if any(name == p or name.startswith(p + ".") for p in blocked):
        raise AssertionError("inference/runtime import: " + name)
    return original(name, *args, **kwargs)
builtins.__import__ = guarded
def audit(event, args):
    if event == "open" and isinstance(args[0], (str, bytes)):
        name = pathlib.Path(args[0]).name.lower()
        if name.startswith(".env") or name in {"config.yaml", "config.yml", "config.json"}:
            raise AssertionError("private/config read: " + name)
    if event in {"socket.connect", "socket.getaddrinfo"}:
        raise AssertionError("network")
sys.addaudithook(audit)
from src.submission_hero import main
assert main(sys.argv[1:]) == 0
'''
    result = subprocess.run([sys.executable, "-B", "-c", script, "--pack", str(pack),
                             "--bundle", str(bundle), "--replay", str(replay),
                             "--output-dir", str(output), "--renderer", "none"],
                            cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr


def test_cli_missing_hero_reports_error(evidence, capsys):
    pack, bundle, replay, proof = evidence
    proof["examples"] = proof["examples"][1:]
    from src.proof_pack import render_html, render_markdown
    write_json(pack / "examples.json", proof)
    (pack / "index.html").write_text(render_html(proof), encoding="utf-8")
    (pack / "PROOF.md").write_text(render_markdown(proof), encoding="utf-8")
    refresh(pack)
    assert main(["--pack", str(pack), "--bundle", str(bundle), "--replay", str(replay),
                 "--print-svg"]) == 1
    assert "missing or ambiguous hero" in capsys.readouterr().err
