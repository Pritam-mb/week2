"""Offline, source-checked submission artwork; no model/config/network access.

From the project root: ``python -B -m src.submission_hero``. The checked-in SVG
must equal the stdlib XML rendering of the validated proof. To update it, use
``--print-svg`` and apply_patch; this command writes only PNG and provenance.
Pillow is optional and renders the small, explicit SVG vocabulary locally.
"""

from __future__ import annotations

import argparse
import json
import platform
import shlex
import sys
import textwrap
import xml.etree.ElementTree as ET
from pathlib import Path
from xml.sax.saxutils import escape, quoteattr

from .evidence_bundle import bundle_files, digest
from .matcher_replay import CODE_FILES
from .proof_pack import collect_proof, read_json, verify_pack

WIDTH, HEIGHT = 1600, 840
HERO = ("360446", "p_nonus")
PAPER, INK, SOFT = "#FAF6EE", "#221C14", "#5B5246"
SVG_NAME = "btod-hero.svg"
PNG_NAME = "btod-hero.png"
PROVENANCE_NAME = "btod-hero.provenance.json"
NS = "http://www.w3.org/2000/svg"


def input_hashes(*roots):
    """Entire manifest inventories, including the manifests themselves."""
    return {f"{root.as_posix()}/{name}": entry["sha256"]
            for root in roots
            for name, entry in {**bundle_files(root), "provenance.json": {
                "sha256": digest(root / "provenance.json")}}.items()}


def select_hero(proof):
    heroes = [row for row in proof["examples"] if row.get("category") == "hero"]
    if len(heroes) != 1 or (heroes[0]["opportunity_id"], heroes[0]["profile_id"]) != HERO:
        raise ValueError("missing or ambiguous hero 360446/p_nonus")
    hero = heroes[0]
    profile, chosen, predictions = (hero["profile"], hero["chosen_restriction"],
                                    hero["predictions"])
    if (profile["id"] != HERO[1] or profile["org_type"] != "nonprofit" or
            profile["us_based"] is not False or
            "United Kingdom" not in profile.get("notes", "") or
            "Constructed profile" not in profile.get("notes", "")):
        raise ValueError("hero must be the constructed UK nonprofit profile")
    if (predictions["code_only"]["verdict"] != "ELIGIBLE" or
            predictions["replay_fine_tuned"]["verdict"] != "NOT_ELIGIBLE" or
            hero["label"]["true_verdict"] != "NOT_ELIGIBLE"):
        raise ValueError("hero verdicts no longer support the comparison")
    if (chosen["quote_verified_against_full_source"] is not True or
            chosen["interpretation"] != "conflict" or
            chosen["rule_family"] != "organizational geography / excluded" or
            "Foreign Organizations" not in chosen["condition"]["quote"] or
            chosen["condition"]["quote"] not in
            predictions["replay_fine_tuned"]["disqualifying_quotes"]):
        raise ValueError("hero lacks a verified actual foreign-organizations disqualifier")
    if (proof["candidate_count"] != len(proof["candidates"]) or
            proof["candidate_count"] != 3 or
            proof["candidate_rule_family_count"] != 1 or
            proof["candidate_profile_count"] != 1):
        raise ValueError("hero scope must remain three pairs / one rule family / one profile")
    fine = proof["summary"]["replay_fine_tuned"]
    if fine["pairs"] != proof["dimensions"]["pairs"] or fine["automatic"] + fine["check"] != fine["pairs"]:
        raise ValueError("inconsistent replay CHECK coverage")
    return hero


def validated_proof(pack, bundle, replay):
    proof = verify_pack(pack)
    hero = select_hero(proof)
    other = [row for row in proof["examples"] if row.get("category") == "another_catch"]
    if len(other) != 1:
        raise ValueError("missing second proof comparison")
    rebuilt = collect_proof(bundle, replay, HERO[0], other[0]["opportunity_id"])
    rebuilt["generation_command"] = proof["generation_command"]
    if rebuilt != proof:
        raise ValueError("published proof differs from revalidated original/replay inputs")
    manifest = read_json(pack / "provenance.json")
    if manifest["input_manifests_sha256"] != {
            f"{root.as_posix()}/provenance.json": digest(root / "provenance.json")
            for root in (bundle, replay)}:
        raise ValueError("proof pack input manifest links differ")
    sources = read_json(bundle / "data/source_text.json")
    if hero["chosen_restriction"]["condition"]["quote"] not in sources[HERO[0]]:
        raise ValueError("hero quote is not an exact substring of full bundled source")
    return proof, hero


def scope_line(proof):
    fine = proof["summary"]["replay_fine_tuned"]
    return (f"Offline development replay · {proof['candidate_count']} pairs / one rule family"
            f" · {fine['check']}/{fine['pairs']} CHECK")


def render_svg(proof):
    """Pure stdlib XML: data is always text, never markup or an asset URL."""
    hero = select_hero(proof)
    lines = [f'<svg xmlns="{NS}" width="1600" height="840" viewBox="0 0 1600 840" '
             'role="img" aria-labelledby="title description">',
             '<title id="title">Grant Fine Print — Opportunity360446 / BTOD proof card</title>',
             '<desc id="description">Generated proof card, not a live application screenshot. '
             'Constructed UK nonprofit; cached baseline LIKELY ELIGIBLE; offline replay '
             'NOT ELIGIBLE. Quote rechecked against bundled source. No inference rerun.</desc>']

    def node(tag, **attrs):
        lines.append(f"<{tag} " + " ".join(
            f'{key.replace("_", "-")}={quoteattr(str(value))}'
            for key, value in attrs.items()) + "/>")

    def rect(x, y, width, height, fill, stroke=None, radius=0):
        attrs = dict(x=x, y=y, width=width, height=height, fill=fill, rx=radius)
        if stroke:
            attrs.update(stroke=stroke, stroke_width=2)
        node("rect", **attrs)

    def text(x, y, value, size=20, fill=INK, family="Arial, sans-serif", weight="normal"):
        # Conservative maximum advance: fail closed instead of clipping new data.
        if len(str(value)) * size > (WIDTH - x - 44) * 2:
            raise ValueError("text exceeds conservative hero layout budget")
        lines.append(f'<text x="{x}" y="{y}" font-family={quoteattr(family)} '
                     f'font-size="{size}" font-weight="{weight}" fill="{fill}">'
                     f'{escape(str(value))}</text>')

    rect(0, 0, 1600, 840, "#EAE2D0")
    rect(36, 36, 1536, 776, INK, radius=8)
    rect(28, 28, 1536, 776, PAPER, INK, 8)
    text(68, 82, "EVIDENCE FIRST / GRANT REVIEW", 17, SOFT, "Consolas, monospace")
    rect(1210, 58, 314, 38, "#F7E37A", INK, 3)
    text(1228, 84, "GENERATED PROOF CARD", 20, weight="bold")
    text(68, 165, "Grant Fine Print", 76, family="Georgia, serif")
    text(70, 210, "The fine print changes the verdict.", 28, SOFT)
    text(1154, 206, "Not a live application screenshot", 20, SOFT)
    node("line", x1=68, y1=237, x2=1524, y2=237, stroke=INK, stroke_width=2)
    text(68, 279, "Opportunity360446 / BTOD", 25, family="Consolas, monospace")
    text(68, 313, "Biomedical Technology Optimization and Dissemination Center", 20, SOFT)
    text(900, 279, hero["profile"]["name"], 27, family="Georgia, serif")
    text(900, 313, "Constructed UK nonprofit · p_nonus · U.S.-based: no", 21, SOFT)
    rect(74, 350, 650, 150, INK, radius=4)
    rect(68, 344, 650, 150, "#EDF3E8", INK, 4)
    text(92, 377, "01 / CODE-ONLY BASELINE", 18, SOFT, "Consolas, monospace")
    text(92, 430, "LIKELY ELIGIBLE", 43, "#3D572E", weight="bold")
    text(92, 468, "Cached development prediction · ELIGIBLE", 20, SOFT)
    node("line", x1=751, y1=419, x2=805, y2=419, stroke=INK, stroke_width=3)
    node("line", x1=792, y1=406, x2=805, y2=419, stroke=INK, stroke_width=3)
    node("line", x1=792, y1=432, x2=805, y2=419, stroke=INK, stroke_width=3)
    rect(842, 350, 688, 150, INK, radius=4)
    rect(836, 344, 688, 150, "#FAECE9", INK, 4)
    text(860, 377, "02 / SOURCE-RULE REPLAY", 18, SOFT, "Consolas, monospace")
    text(860, 430, "NOT ELIGIBLE", 43, "#8A2C1F", weight="bold")
    text(860, 468, "Cached fine-tuned conditions · interpreter conflict", 20, SOFT)
    text(68, 541, "VERBATIM RESTRICTION / VERIFIED AGAINST BUNDLED FULL SOURCE", 18,
         SOFT, "Consolas, monospace")
    quote = hero["chosen_restriction"]["condition"]["quote"]
    wrapped = textwrap.wrap(quote, width=60, break_long_words=False, break_on_hyphens=False)
    if len(wrapped) > 2:
        raise ValueError("verified quote exceeds two-line hero layout")
    for i, line in enumerate(wrapped):
        y = 591 + i * 45
        rect(84, y - 30, min(1412, len(line) * 18 + 22), 39, "#F7E37A", radius=2)
        text(96, y, line, 31, family="Georgia, serif")
    text(68, 688, "Organizational geography conflicts with this profile. Confirm in the original notice.",
         22, SOFT)
    node("line", x1=68, y1=720, x2=1524, y2=720, stroke="#BDB39E", stroke_width=1)
    text(68, 758, scope_line(proof), 23, SOFT)
    text(68, 790, "No inference rerun · Reused development set · Illustrative pairs, not independent observations", 18, SOFT)
    lines.append("</svg>")
    return "\n".join(lines) + "\n"


def local_font(ImageFont, family, bold, size):
    serif, mono = family.startswith("Georgia"), family.startswith("Consolas")
    names = (["georgia.ttf", "DejaVuSerif.ttf"] if serif else
             ["consola.ttf", "DejaVuSansMono.ttf"] if mono else
             ["arialbd.ttf", "DejaVuSans-Bold.ttf"] if bold else
             ["arial.ttf", "DejaVuSans.ttf"])
    for name in names:
        for candidate in (Path("C:/Windows/Fonts") / name, Path(name)):
            try:
                return ImageFont.truetype(str(candidate), size)
            except OSError:
                continue
    raise OSError(f"no installed local font for {family}; no fonts downloaded")


def render_png(svg, output, renderer="auto"):
    """Render our exact rect/line/text subset, with measured overflow checks."""
    if renderer == "none":
        return {"name": "none", "png_created": False, "blocker": "SVG-only explicitly requested"}
    try:
        from PIL import Image, ImageDraw, ImageFont, __version__
    except ImportError:
        if renderer == "pillow":
            raise ValueError("Pillow is not installed; no dependencies installed")
        return {"name": "none", "png_created": False,
                "blocker": "Pillow is not installed; use the SVG (no dependencies installed)"}
    scale = 2
    image = Image.new("RGB", (WIDTH * scale, HEIGHT * scale), PAPER)
    draw = ImageDraw.Draw(image)
    fonts, used = {}, {}
    root = ET.fromstring(svg)
    for element in root:
        tag, a = element.tag.removeprefix(f"{{{NS}}}"), element.attrib
        if tag in {"title", "desc"}:
            continue
        if tag == "rect":
            x, y, w, h = (float(a[key]) * scale for key in ("x", "y", "width", "height"))
            draw.rounded_rectangle((x, y, x + w, y + h), radius=float(a["rx"]) * scale,
                                   fill=a["fill"], outline=a.get("stroke"),
                                   width=int(float(a.get("stroke-width", 0)) * scale))
        elif tag == "line":
            xy = [float(a[key]) * scale for key in ("x1", "y1", "x2", "y2")]
            draw.line(xy, fill=a["stroke"], width=int(float(a["stroke-width"]) * scale))
        elif tag == "text":
            key = (a["font-family"], a["font-weight"], int(a["font-size"]))
            if key not in fonts:
                fonts[key] = local_font(ImageFont, key[0], key[1] == "bold", key[2] * scale)
                path = Path(fonts[key].path)
                used[path.name] = digest(path)
            font = fonts[key]
            x, y = float(a["x"]) * scale, float(a["y"]) * scale
            text = element.text or ""
            box = draw.textbbox((x, y), text, font=font, anchor="ls")
            if box[0] < 0 or box[1] < 0 or box[2] > (WIDTH - 44) * scale or box[3] > 800 * scale:
                raise ValueError(f"measured text overflow: {text}")
            draw.text((x, y), text, font=font, fill=a["fill"], anchor="ls")
        else:
            raise ValueError(f"unsupported SVG element for local PNG renderer: {tag}")
    image = image.resize((WIDTH, HEIGHT), Image.Resampling.LANCZOS)
    image.save(output, format="PNG")
    with Image.open(output) as restored:
        if restored.format != "PNG" or restored.size != (WIDTH, HEIGHT):
            raise ValueError("PNG roundtrip dimensions/format mismatch")
    return {"name": "Pillow", "version": __version__, "png_created": True,
            "method": "restricted SVG rect/line/text rasterizer; 2x supersampling",
            "fonts_sha256": dict(sorted(used.items()))}


def generate(pack=Path("reports/proof_pack"), bundle=Path("results/evidence"),
             replay=Path("results/source_semantics"), output=Path("docs/images"),
             *, renderer="auto", print_svg=False):
    pack, bundle, replay, output = map(Path, (pack, bundle, replay, output))
    for root in (pack, bundle, replay):
        if output.resolve().is_relative_to(root.resolve()):
            raise ValueError("hero output must be separate from proof/evidence/replay inputs")
    before = input_hashes(pack, bundle, replay)
    proof, hero = validated_proof(pack, bundle, replay)
    svg = render_svg(proof)
    if print_svg:
        return svg
    # SVG edits use apply_patch, never an unreviewed overwrite of the source art.
    svg_path, png_path = output / SVG_NAME, output / PNG_NAME
    for name in (SVG_NAME, PNG_NAME, PROVENANCE_NAME):
        if (output / name).is_symlink():
            raise ValueError("hero output files must not be symlinks")
    if svg_path.read_text(encoding="utf-8") != svg:
        raise ValueError("SVG differs from verified proof; use --print-svg and apply_patch")
    renderer_info = render_png(svg, png_path, renderer)
    if not renderer_info["png_created"] and png_path.exists():
        raise ValueError("unverified existing PNG; refusing to publish stale provenance")
    if before != input_hashes(pack, bundle, replay):
        raise ValueError("proof/evidence/replay inputs changed during hero generation")
    command = ["python", "-B", "-m", "src.submission_hero", "--pack", pack.as_posix(),
               "--bundle", bundle.as_posix(), "--replay", replay.as_posix(),
               "--output-dir", output.as_posix(), "--renderer", renderer]
    project = Path(__file__).resolve().parents[1]
    code_names = sorted({f"src/{name}" for name in CODE_FILES} |
                        {"src/proof_pack.py", "src/submission_hero.py", "tests/test_submission_hero.py"})
    artifacts = [svg_path] + ([png_path] if renderer_info["png_created"] else [])
    provenance = {
        "schema_version": 1, "generation_command": shlex.join(command),
        "generation_cwd": "project root", "python_version": platform.python_version(),
        "artifact_kind": "generated proof card, not a live application screenshot",
        "dimensions": {"width": WIDTH, "height": HEIGHT},
        "hero": {"opportunity_id": HERO[0], "profile_id": HERO[1],
                 "profile": hero["profile"], "baseline_system": "code_only",
                 "baseline_verdict": "ELIGIBLE", "baseline_display": "LIKELY ELIGIBLE",
                 "replay_system": "replay_fine_tuned", "replay_verdict": "NOT_ELIGIBLE",
                 "replay_display": "NOT ELIGIBLE",
                 "exact_quote": hero["chosen_restriction"]["condition"]["quote"],
                 "full_source_sha256": hero["source"]["full_source_sha256"]},
        "visible_scope": scope_line(proof), "limits": proof["limits"],
        "inference_rerun": False, "full_source_semantically_adjudicated_by_software": False,
        "verification": {"verify_pack": True, "collect_proof_equal": True,
                         "exact_quote_substring": True, "inputs_unchanged": True,
                         "svg_equals_stdlib_render": True},
        "svg_update_command": shlex.join(command + ["--print-svg"]),
        "svg_update_method": "Apply printed XML with apply_patch; generator checks equality",
        "renderer": renderer_info, "input_sha256": dict(sorted(before.items())),
        "code_sha256": {name: digest(project / name) for name in code_names},
        "hash_scope": "Input payloads and manifests; output SVG/PNG, excluding this sidecar.",
        "files": {path.name: {"sha256": digest(path), "bytes": path.stat().st_size}
                  for path in artifacts},
    }
    (output / PROVENANCE_NAME).write_text(
        json.dumps(provenance, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return provenance


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pack", type=Path, default=Path("reports/proof_pack"))
    parser.add_argument("--bundle", type=Path, default=Path("results/evidence"))
    parser.add_argument("--replay", type=Path, default=Path("results/source_semantics"))
    parser.add_argument("--output-dir", type=Path, default=Path("docs/images"))
    parser.add_argument("--renderer", choices=("auto", "pillow", "none"), default="auto")
    parser.add_argument("--print-svg", action="store_true")
    args = parser.parse_args(argv)
    try:
        result = generate(args.pack, args.bundle, args.replay, args.output_dir,
                          renderer=args.renderer, print_svg=args.print_svg)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if args.print_svg:
        print(result, end="")
    else:
        print(f"{args.output_dir / SVG_NAME}: {WIDTH}x{HEIGHT}; proof and inputs revalidated")
        print(f"PNG: {result['renderer']}")
        print(f"Provenance: {args.output_dir / PROVENANCE_NAME}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
