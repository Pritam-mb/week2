"""Publish a small offline proof pack from the original bundle and FINAL replay.

No extraction, inference, environment access, or configuration loading occurs.
Run from the project root with ``python -B -m src.proof_pack --help``.
"""

from __future__ import annotations

import argparse
import html
import json
import shlex
import sys
from pathlib import Path

from . import eval as evaluator
from .evidence_bundle import bundle_files, digest, write_json
from .matcher_replay import (
    CODE_FILES, canonical_hash, conditions_from_list, load_evidence, read_json,
    sha256, validate_coverage, validate_snapshot,
)
from .models import Profile, normalize_ws, text_hash
from .source_rules import interpret_source_rule
from .verify import is_verbatim_quote, verify_conditions


BANNER = "Offline development evidence preview—not live inference"
FINAL_SYSTEMS = {"code_only", "original_prompted", "original_fine_tuned",
                 "replay_prompted", "replay_fine_tuned"}
PRESENTED_FIELDS = ("verdict", "conditions", "disqualifying_quotes", "check_quotes",
                    "check_reasons", "proposed_disqualifier_quotes")
STATUS_QUOTES = (
    "This is a notice of intent and no applications are being accepted at this time.",
    "We are not accepting applications at this time.",
)
LIMITS = (
    "Reused development set; single-author labels; constructed profiles. Pairs share "
    "notices and profiles and are not independent observations. No generalization "
    "claim or causal fine-tuning improvement estimate is supported. Cached backend "
    "names do not authenticate model/checkpoint identity. No inference was rerun. "
    "Software re-checks quote presence against the full bundled source and interprets "
    "only the chosen restriction; the full source is NOT semantically adjudicated "
    "by software. Hashes establish consistency, not external authenticity."
)


def checked_manifest(root):
    manifest = read_json(root / "provenance.json")
    if manifest.get("schema_version") != 1 or manifest.get("files") != bundle_files(root):
        raise ValueError(f"manifest payload SHA256/file inventory mismatch: {root}")
    return manifest


def load_inputs(bundle, replay):
    """Validate both entire payload inventories before selecting any examples."""
    original_manifest = checked_manifest(bundle)
    final_manifest = checked_manifest(replay)
    labels, profiles, originals, sources = load_evidence(bundle)
    if read_json(bundle / "data/source_text.json") != sources:
        raise ValueError("full source copy mismatch")
    for name, entry in original_manifest.get("input_copies", {}).items():
        if entry["sha256"] != original_manifest["files"][name]["sha256"]:
            raise ValueError(f"original input copy hash mismatch: {name}")
    evidence_hash = digest(bundle / "provenance.json")
    if final_manifest.get("evidence_provenance_sha256") != evidence_hash:
        raise ValueError("FINAL evidence provenance hash mismatch")
    expected_inputs = {"data/labels.csv", "provenance.json"}
    expected_inputs.update(f"data/profiles/{p.name}"
                           for p in (bundle / "data/profiles").glob("*.json"))
    expected_inputs.update(f"predictions/{name}.jsonl" for name in originals)
    if final_manifest.get("inputs_sha256") != {
            name: digest(bundle / name) for name in sorted(expected_inputs)}:
        raise ValueError("FINAL input payload hashes/coverage mismatch")
    if (final_manifest.get("notices"), final_manifest.get("profiles"),
            final_manifest.get("pairs")) != (len(sources), len(profiles), len(labels)):
        raise ValueError("FINAL dimensions/coverage mismatch")
    snapshot_path = replay / "conditions_snapshot.json"
    snapshot = read_json(snapshot_path)
    raw = validate_snapshot(snapshot, sources, evidence_hash)
    if (final_manifest.get("mode") == "snapshot" and
            final_manifest.get("snapshot_input_sha256") != digest(snapshot_path)):
        raise ValueError("FINAL snapshot input hash mismatch")
    source_records = {
        key: {"opportunity_id": record["opportunity_id"],
              "source_sha256": record["source_sha256"],
              "conditions_sha256": {name: entry["conditions_sha256"]
                                    for name, entry in record["systems"].items()}}
        for key, record in snapshot["sources"].items()}
    if final_manifest.get("sources") != source_records:
        raise ValueError("FINAL source/condition hashes mismatch")
    # The interpreter being used must be the one that produced this FINAL replay.
    code_root = Path(__file__).parent
    if final_manifest.get("code_sha256") != {
            f"src/{name}": digest(code_root / name) for name in CODE_FILES}:
        raise ValueError("FINAL replay code hashes differ from current code")
    predictions = {}
    for path in sorted((replay / "predictions").glob("*.jsonl")):
        rows = evaluator.load_predictions(path)
        validate_coverage(rows, set(labels), path.name)
        for row in rows:
            conditions_from_list(row.get("conditions", []), path.name)
        predictions[path.stem] = {(r["opportunity_id"], r["profile_id"]): r for r in rows}
    if set(predictions) != FINAL_SYSTEMS:
        raise ValueError("FINAL prediction system coverage mismatch")
    for system, by_notice in raw.items():
        for (oid, _), row in predictions[f"replay_{system}"].items():
            verified = verify_conditions(by_notice[oid], sources[oid]).verified
            if row.get("conditions") != [c.to_dict() for c in verified]:
                raise ValueError(f"FINAL verified condition mismatch: {oid}/{system}")
    for name in originals:
        target = name if name == "code_only" else f"original_{name}"
        if (bundle / f"predictions/{name}.jsonl").read_bytes() != (
                replay / f"predictions/{target}.jsonl").read_bytes():
            raise ValueError(f"FINAL original prediction copy mismatch: {name}")
    metrics = {name: evaluator.evaluate_system(list(rows.values()), labels, {})
               for name, rows in predictions.items()}
    if read_json(replay / "eval.json").get("systems") != metrics:
        raise ValueError("FINAL metrics disagree with current prediction rows")
    return labels, profiles, sources, predictions, raw, metrics


def chosen_restriction(row, profile, source):
    """Use an actual current disqualifier, never substitute the label sentence."""
    for quote in row.get("disqualifying_quotes", []):
        if not is_verbatim_quote(quote, source):
            raise ValueError("current disqualifier is not present in full source")
        for condition in conditions_from_list(row["conditions"], "chosen restriction"):
            if normalize_ws(condition.quote) != normalize_ws(quote):
                continue
            outcome = interpret_source_rule(condition, profile)
            if outcome == "conflict":
                opposite = Profile.from_dict({**profile.to_dict(), "us_based": not profile.us_based})
                contrast = interpret_source_rule(condition, opposite)
                family = ("organizational geography" if contrast == "satisfied"
                          else "organization type")
                return {
                    "condition": condition.to_dict(), "quote_verified_against_full_source": True,
                    "interpreter": "src.source_rules.interpret_source_rule",
                    "interpretation": outcome,
                    "membership": {
                        "in_quoted_group": condition.polarity.value == "excluded",
                        "derived_from": "interpreter conflict result and condition polarity",
                    },
                    "rule_family": f"{family} / {condition.polarity.value}",
                    "family_basis": "interpreter contrast with only us_based flipped",
                    "opposite_geography_interpretation": contrast,
                }
    raise ValueError("candidate has no source-verified interpreter conflict")


def summary(metrics, pairs):
    result = {}
    for name in ("code_only", "replay_fine_tuned", "replay_prompted"):
        counts = metrics[name]
        automatic = counts["automatic_decision_accuracy"]
        result[name] = {"pairs": pairs, "automatic": automatic["n"],
                        "check": counts["human_read_share"]["k"],
                        "automatic_label_agreement": automatic}
    return result


def example_record(key, category, labels, profiles, sources, predictions, bundle, replay):
    oid, pid = key
    source = sources[oid]
    return {
        "category": category, "opportunity_id": oid, "profile_id": pid,
        "profile": profiles[pid].to_dict(),
        "label": {field: labels[key][field]
                  for field in ("true_verdict", "disqualifying_sentence")},
        "source": {"path": (bundle / "data/source_text.json").as_posix(),
                   "key": oid, "full_source_sha256": sha256(source.encode("utf-8")),
                   "normalized_source_sha256": text_hash(source),
                   "file_sha256": digest(bundle / "data/source_text.json"),
                   "full_source_semantically_adjudicated_by_software": False},
        "label_pointer": {"path": (bundle / "data/labels.csv").as_posix(),
                          "pair": [oid, pid], "sha256": digest(bundle / "data/labels.csv")},
        "profile_pointer": {"path": (bundle / f"data/profiles/{pid}.json").as_posix(),
                            "sha256": digest(bundle / f"data/profiles/{pid}.json")},
        "predictions": {
            name: {field: rows[key].get(field, [] if field != "verdict" else None)
                   for field in PRESENTED_FIELDS}
            for name, rows in predictions.items()},
        "prediction_pointers": {
            name: {"path": (replay / f"predictions/{name}.jsonl").as_posix(),
                   "pair": [oid, pid], "sha256": digest(replay / f"predictions/{name}.jsonl")}
            for name in predictions},
    }


def collect_proof(bundle, replay, hero_id, second_id):
    labels, profiles, sources, predictions, raw, metrics = load_inputs(bundle, replay)
    candidates = []
    for key in sorted(labels):
        if (labels[key]["true_verdict"] == "NOT_ELIGIBLE" and
                predictions["code_only"][key]["verdict"] == "ELIGIBLE" and
                predictions["replay_fine_tuned"][key]["verdict"] == "NOT_ELIGIBLE"):
            record = example_record(key, "restriction_catch", labels, profiles, sources,
                                    predictions, bundle, replay)
            record["chosen_restriction"] = chosen_restriction(
                predictions["replay_fine_tuned"][key], profiles[key[1]], sources[key[0]])
            candidates.append(record)
    by_pair = {(r["opportunity_id"], r["profile_id"]): r for r in candidates}
    hero_key = (hero_id, "p_nonus")
    if hero_key not in by_pair:
        raise ValueError("hero must be a true NOT_ELIGIBLE baseline-ELIGIBLE FINAL catch")
    other_keys = [key for key in by_pair if key != hero_key]
    second_key = (second_id, "p_nonus") if second_id else next(iter(other_keys), None)
    if second_key not in other_keys:
        raise ValueError("second example must be another qualifying catch")
    honest_key = ("328026", "p_forprofit")
    honest = example_record(honest_key, "honest_CHECK", labels, profiles, sources,
                            predictions, bundle, replay)
    current = predictions["replay_fine_tuned"][honest_key]
    extracted = raw["fine_tuned"][honest_key[0]]
    if (labels[honest_key]["true_verdict"] != "CHECK" or current["verdict"] != "CHECK" or
            predictions["original_fine_tuned"][honest_key]["verdict"] != "ELIGIBLE" or
            len(extracted) != 1 or not extracted[0].quote.strip() or
            not current.get("check_reasons")):
        raise ValueError("honest CHECK must retain its original/current verdicts and nonempty extraction")
    omitted = [quote for quote in STATUS_QUOTES
               if is_verbatim_quote(quote, sources[honest_key[0]]) and
               not any(is_verbatim_quote(quote, c.quote) for c in extracted)]
    if not omitted:
        raise ValueError("honest CHECK is missing verified omitted application-status context")
    honest["why_check"] = current["check_reasons"]
    honest["extraction_review"] = {
        "raw_condition_count": len(extracted),
        "raw_conditions_sha256": canonical_hash([c.to_dict() for c in extracted]),
        "condition_interpretations": [interpret_source_rule(c, profiles[honest_key[1]])
                                      for c in extracted],
        "omitted_application_status_quotes": omitted,
        "context_note": "One nonempty mixed applicant-list condition was extracted. "
                        "The actual CHECK reason concerns applicant grouping. The separate "
                        "not-accepting-applications text is present in full source but omitted "
                        "from extraction; it is context, not the recorded CHECK reason.",
    }
    counts = summary(metrics, len(labels))
    return {
        "schema_version": 1, "banner": BANNER, "limits": LIMITS,
        "final_replay": replay.as_posix(),
        "dimensions": {"notices": len(sources), "profiles": len(profiles), "pairs": len(labels)},
        "summary": counts, "candidate_count": len(candidates),
        "candidate_selection": "ALL original code_only ELIGIBLE -> CURRENT FINAL "
                               "replay_fine_tuned NOT_ELIGIBLE pairs labelled NOT_ELIGIBLE; "
                               "lexical pair order. Every candidate must have a verified "
                               "actual disqualifier interpreted as conflict.",
        "candidate_profile_count": len({r["profile_id"] for r in candidates}),
        "candidate_rule_family_count": len({r["chosen_restriction"]["rule_family"]
                                            for r in candidates}),
        "candidates": candidates,
        "example_selection": "Hero selected by --hero-id with p_nonus; second selected by "
                             "--second-id or first other lexical candidate; honest CHECK fixed "
                             "at 328026/p_forprofit. Illustrative, not a random sample.",
        "examples": [{**by_pair[hero_key], "category": "hero"},
                     {**by_pair[second_key], "category": "another_catch"}, honest],
    }


def headline(proof):
    fine = proof["summary"]["replay_fine_tuned"]
    agreement = fine["automatic_label_agreement"]
    return (f"FINAL fine-tuned replay: {fine['automatic']}/{fine['pairs']} automatic, "
            f"{fine['check']} CHECK, {agreement['k']}/{agreement['n']} automatic label agreement.")


def coverage_note(proof):
    baseline = proof["summary"]["code_only"]
    fine = proof["summary"]["replay_fine_tuned"]
    comparison = "greater" if baseline["automatic"] > fine["automatic"] else "no greater"
    agreement = baseline["automatic_label_agreement"]
    return (f"The code-only baseline has {comparison} automatic coverage: "
            f"{baseline['automatic']}/{baseline['pairs']} automatic, {baseline['check']} CHECK; "
            f"{agreement['k']}/{agreement['n']} automatic label agreement. "
            "Agreement on a small automatic subset must be read alongside abstention.")


def catch_scope_note(proof):
    if proof["candidate_profile_count"] == proof["candidate_rule_family_count"] == 1:
        candidate = proof["candidates"][0]
        return (f"All {proof['candidate_count']} catches share profile {candidate['profile_id']} "
                f"and rule family {candidate['chosen_restriction']['rule_family']}. "
                "They do not demonstrate broad rule coverage.")
    return (f"{proof['candidate_count']} catches span {proof['candidate_profile_count']} profile(s) "
            f"and {proof['candidate_rule_family_count']} interpreted rule families. "
            "These illustrative catches do not demonstrate generalization.")


def render_markdown(proof):
    lines = ["# Offline public proof pack", "", BANNER, "", headline(proof), "",
             coverage_note(proof), "", f"FINAL input: `{proof['final_replay']}`.", "",
             "## All qualifying catches", "", proof["candidate_selection"], "",
             catch_scope_note(proof), "",
             "| Notice | Profile | Label | Code-only | FINAL fine-tuned | Interpreter |",
             "|---|---|---|---|---|---|"]
    for row in proof["candidates"]:
        lines.append(f"| {row['opportunity_id']} | {row['profile_id']} | NOT_ELIGIBLE | "
                     "ELIGIBLE | NOT_ELIGIBLE | conflict |")
    lines += ["", "## Three illustrative comparisons", "", proof["example_selection"]]
    for row in proof["examples"]:
        preds = row["predictions"]
        lines += ["", f"### {row['category']}: {row['opportunity_id']} / {row['profile_id']}",
                  f"Label **{row['label']['true_verdict']}**; code-only "
                  f"**{preds['code_only']['verdict']}**; original fine-tuned "
                  f"**{preds['original_fine_tuned']['verdict']}**; FINAL fine-tuned "
                  f"**{preds['replay_fine_tuned']['verdict']}**."]
        if "chosen_restriction" in row:
            chosen = row["chosen_restriction"]
            lines += ["", "> " + html.escape(chosen["condition"]["quote"]), "",
                      "Actual FINAL disqualifier re-verified against full source; interpreter "
                      f"returns **{chosen['interpretation']}**. Membership in the quoted group: "
                      f"**{chosen['membership']['in_quoted_group']}**, derived via the interpreter."]
        else:
            lines += ["", "**Why CHECK (actual prediction reason):** " +
                      " ".join(html.escape(r) for r in row["why_check"]), "",
                      row["extraction_review"]["context_note"]]
            lines += ["", *["> " + html.escape(q) for q in
                            row["extraction_review"]["omitted_application_status_quotes"]]]
        lines += ["", f"Full source SHA256: `{row['source']['full_source_sha256']}`; "
                  f"pointer `{row['source']['path']}` key `{row['source']['key']}`."]
    lines += ["", "## Scope and reproduction", "", proof["limits"], "",
              "Both input manifests' entire payload inventories and hashes, exact pair coverage "
              "for every prediction system, snapshot/source hashes, original copies and FINAL "
              "metrics were checked. Inputs are read only. Existing output directories are refused.",
              "", "From the project root (use a fresh output directory to repeat):", "", "```text",
              proof["generation_command"], "```", "",
              "`examples.json` contains all candidates, the three examples, conditions, actual "
              "review reasons, label/profile/prediction pointers and full-source hashes; it omits "
              "full raw source/contact payloads. `provenance.json` records input manifest hashes, "
              "current code/test hashes, original replay code hashes and output payload hashes. "
              "Open `index.html` directly for the self-contained comparison preview.", ""]
    return "\n".join(lines)


def render_html(proof):
    def esc(value):
        return html.escape(str(value), quote=True)

    parts = ["<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">",
             '<meta name="viewport" content="width=device-width, initial-scale=1">',
             "<title>Grant Fine Print · Offline proof pack</title><style>",
             "*{box-sizing:border-box}body{margin:0;background:#f4f6f8;color:#172635;"
             "font:16px/1.6 system-ui,sans-serif}main{max-width:1060px;margin:auto;padding:32px 20px}"
             "header,section{background:white;border:1px solid #dce3e9;border-radius:12px;"
             "padding:24px;margin-bottom:22px}.banner{color:#793f04;font-weight:700}"
             "h1,h2,h3{line-height:1.25}h1{margin-top:8px}.scroll{overflow-x:auto}"
             "table{width:100%;border-collapse:collapse}th,td{text-align:left;padding:10px;"
             "border-bottom:1px solid #dce3e9}th{background:#eff4f8}blockquote{margin:16px 0;"
             "padding:12px 18px;border-left:4px solid #287267;background:#f0f8f6}"
             "code,pre{font-size:.85em;overflow-wrap:anywhere}pre{white-space:pre-wrap;"
             "background:#f4f6f8;padding:14px}summary{cursor:pointer;font-weight:600}"
             ".muted{color:#52616e}.hash{font-size:.8em}a{color:#145a91}"
             "</style></head><body><main><header>",
             f'<p class="banner">{esc(BANNER)}</p><h1>Grant Fine Print</h1>',
             f"<h2>{esc(headline(proof))}</h2><p>{esc(coverage_note(proof))}</p>",
             f'<p class="muted">FINAL replay: <code>{esc(proof["final_replay"])}</code></p>',
             '<a href="PROOF.md">Proof notes</a> · <a href="examples.json">Structured evidence</a> · '
             '<a href="provenance.json">Hashes and command</a></header>']
    for row in proof["examples"]:
        preds = row["predictions"]
        parts += [f"<section><h2>{esc(row['category'])}: {esc(row['opportunity_id'])} / "
                  f"{esc(row['profile_id'])}</h2>",
                  f"<p>{esc(row['profile']['name'])} · {esc(row['profile']['org_type'])} · "
                  f"U.S.-based: {esc(row['profile']['us_based'])}</p>",
                  '<div class="scroll"><table><thead><tr><th>Original label</th>'
                  '<th>Code-only baseline</th><th>Original fine-tuned</th>'
                  '<th>CURRENT FINAL fine-tuned</th></tr></thead><tbody><tr>',
                  *[f"<td><strong>{esc(verdict)}</strong></td>" for verdict in (
                      row["label"]["true_verdict"], preds["code_only"]["verdict"],
                      preds["original_fine_tuned"]["verdict"], preds["replay_fine_tuned"]["verdict"])],
                  "</tr></tbody></table></div>"]
        if "chosen_restriction" in row:
            chosen = row["chosen_restriction"]
            parts += ["<h3>Verified restriction</h3>",
                      f"<blockquote>{esc(chosen['condition']['quote'])}</blockquote>",
                      f"<p>Quote present in full source. Interpreter: <b>{esc(chosen['interpretation'])}</b>. "
                      f"Membership in quoted group: <b>{esc(chosen['membership']['in_quoted_group'])}</b> "
                      "(derived from interpreter result and polarity).</p>"]
        else:
            parts += ["<h3>Why CHECK</h3><ul>",
                      *[f"<li>{esc(reason)}</li>" for reason in row["why_check"]], "</ul>",
                      f"<p>{esc(row['extraction_review']['context_note'])}</p>",
                      *[f"<blockquote>{esc(q)}</blockquote>" for q in
                        row["extraction_review"]["omitted_application_status_quotes"]]]
        parts += ["<details><summary>Prediction conditions and relevant quotes</summary>",
                  f"<pre>{esc(json.dumps(preds, indent=2, ensure_ascii=False))}</pre></details>",
                  "<details><summary>Original label and full-source hash pointers</summary>",
                  f"<pre>{esc(json.dumps({k: row[k] for k in ('label', 'source', 'label_pointer', 'profile_pointer', 'prediction_pointers')}, indent=2, ensure_ascii=False))}</pre>",
                  "</details></section>"]
    parts += ["<section><h2>All qualifying catches</h2>",
              f"<p>{esc(proof['candidate_selection'])}</p>",
              f"<p>{esc(catch_scope_note(proof))}</p><ul>",
              *[f"<li>{esc(r['opportunity_id'])} / {esc(r['profile_id'])}: "
                "ELIGIBLE → NOT_ELIGIBLE; label NOT_ELIGIBLE; interpreter conflict.</li>"
                for r in proof["candidates"]],
              "</ul></section><section><h2>Evidence boundaries and reproduction</h2>",
              f"<p>{esc(proof['limits'])}</p><p>{esc(proof['example_selection'])}</p>",
              f"<pre>{esc(proof['generation_command'])}</pre>",
              "<p>Run from the project root using a fresh output directory. "
              "No external dependencies, scripts, remote assets, or live inference are used "
              "by this preview.</p></section></main></body></html>\n"]
    return "\n".join(parts)


def verify_pack(output):
    """Check persisted output hashes and roundtrip all three public views."""
    output = Path(output)
    manifest = checked_manifest(output)
    proof = read_json(output / "examples.json")
    if manifest["generation_command"] != proof["generation_command"]:
        raise ValueError("proof command roundtrip mismatch")
    for name, content in (("PROOF.md", render_markdown(proof)),
                          ("index.html", render_html(proof))):
        if (output / name).read_text(encoding="utf-8") != content:
            raise ValueError(f"proof roundtrip mismatch: {name}")
    return proof


def generate_pack(bundle=Path("results/evidence"), replay=Path("results/source_semantics"),
                  output=Path("reports/proof_pack"), *, hero_id="360446", second_id=None):
    bundle, replay, output = Path(bundle), Path(replay), Path(output)
    if output.exists() or output.is_symlink():
        raise ValueError(f"output already exists; use a fresh directory: {output}")
    if any(output.resolve().is_relative_to(root.resolve()) for root in (bundle, replay)):
        raise ValueError("output must be separate from both input directories")
    before = {root: (digest(root / "provenance.json"), bundle_files(root))
              for root in (bundle, replay)}
    proof = collect_proof(bundle, replay, str(hero_id), second_id)
    command = ["python", "-B", "-m", "src.proof_pack", "--bundle", bundle.as_posix(),
               "--replay", replay.as_posix(), "--output", output.as_posix(),
               "--hero-id", str(hero_id)]
    if second_id is not None:
        command += ["--second-id", str(second_id)]
    proof["generation_command"] = shlex.join(command)
    output.mkdir(parents=True)
    write_json(output / "examples.json", proof)
    (output / "PROOF.md").write_text(render_markdown(proof), encoding="utf-8")
    (output / "index.html").write_text(render_html(proof), encoding="utf-8")
    restored = read_json(output / "examples.json")
    if restored != proof:
        raise ValueError("examples JSON roundtrip mismatch")
    for root, original in before.items():
        if (digest(root / "provenance.json"), bundle_files(root)) != original:
            raise ValueError(f"inputs changed during generation: {root}")
    project = Path(__file__).resolve().parents[1]
    code_names = {f"src/{name}" for name in CODE_FILES}
    code_names.update({"src/__init__.py", "src/proof_pack.py", "tests/test_proof_pack.py"})
    write_json(output / "provenance.json", {
        "schema_version": 1, "generation_command": proof["generation_command"],
        "generation_cwd": "project root", "inference_rerun": False,
        "full_source_semantically_adjudicated_by_software": False,
        "inputs_unchanged_verified": True, "json_roundtrip_verified": True,
        "input_manifests_sha256": {root.as_posix() + "/provenance.json": value[0]
                                   for root, value in before.items()},
        "code_sha256": {name: digest(project / name) for name in sorted(code_names)},
        "final_replay_code_sha256": read_json(replay / "provenance.json")["code_sha256"],
        "hash_scope": "All output payload files except this manifest itself.",
        "files": bundle_files(output),
    })
    if verify_pack(output) != proof:
        raise ValueError("persisted proof roundtrip mismatch")
    return proof


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, default=Path("results/evidence"))
    parser.add_argument("--replay", type=Path, default=Path("results/source_semantics"))
    parser.add_argument("--output", type=Path, default=Path("reports/proof_pack"))
    parser.add_argument("--hero-id", default="360446")
    parser.add_argument("--second-id", help="otherwise the first other lexical candidate")
    args = parser.parse_args(argv)
    try:
        proof = generate_pack(args.bundle, args.replay, args.output,
                              hero_id=args.hero_id, second_id=args.second_id)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(headline(proof))
    print(coverage_note(proof))
    print(f"All qualifying catches: {proof['candidate_count']}; "
          f"examples: {len(proof['examples'])}")
    print(f"Preview: {args.output / 'index.html'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
