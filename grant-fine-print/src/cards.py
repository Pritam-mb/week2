"""Printable one-page cards: per-profile verdicts grouped by outcome.

The card is deliberately self-contained HTML with inline CSS and a small
``@media print`` block, so it can be opened in any browser and printed to a
single page without a build step.
"""

from __future__ import annotations

import argparse
import html
import json
from datetime import date
from pathlib import Path
from typing import Any, Optional

from .config import get as cfg_get
from .config import load_config
from .io_utils import load_opportunities, load_profiles, write_text
from .models import Condition, Opportunity, Profile, Verdict, VerdictRow

BRAND = "Grant Fine Print"
CONFIRM_LINE = "Confirm in the original notice."
LEGAL_NOTE = "This card is not legal advice."

# Display order and labels for the three verdict buckets.
SECTION_ORDER: list[tuple[Verdict, str]] = [
    (Verdict.ELIGIBLE, "LIKELY ELIGIBLE"),
    (Verdict.NOT_ELIGIBLE, "NOT ELIGIBLE"),
    (Verdict.CHECK, "CHECK"),
]

# Set by render_all so render_card honours the caller's config object.
_ACTIVE_CONFIG: Optional[dict[str, Any]] = None

_STYLE_TEMPLATE = """\
:root { --ink: #1a1a1a; --muted: #666; --rule: #d0d0d0; }
* { box-sizing: border-box; }
html { overflow-x: hidden; }
body {
  font-family: Georgia, "Times New Roman", serif;
  color: var(--ink); margin: 0; padding: clamp(14px, 4vw, 24px); line-height: 1.35;
  overflow-wrap: anywhere;
}
.card { max-width: 100%; }
header { border-bottom: 2px solid var(--ink); margin-bottom: 16px; padding-bottom: 8px; }
.brand { font-size: 13px; letter-spacing: 2px; text-transform: uppercase; color: var(--muted); }
h1 { font-size: 22px; margin: 4px 0; }
.meta { font-size: 12px; color: var(--muted); }
.confirm { font-weight: bold; margin-top: 8px; }
.legal { font-size: 11px; font-style: italic; color: var(--muted); }
h2 {
  font-size: 15px; text-transform: uppercase; letter-spacing: 1px;
  border-bottom: 1px solid var(--rule); margin: 18px 0 8px; padding-bottom: 3px;
}
.verdict-section.not-eligible h2 { color: #8a1f1f; }
.verdict-section.check h2 { color: #8a6a00; }
.row {
  border: 1px solid var(--rule); border-radius: 4px; padding: 8px 10px;
  margin-bottom: 8px; break-inside: avoid; page-break-inside: avoid;
}
.row .head { font-weight: bold; font-size: 13px; }
.row .head .opp-number { font-family: "Courier New", monospace; }
.row .facts { font-size: 12px; color: var(--muted); margin-top: 2px; }
.link { overflow-wrap: anywhere; word-break: break-word; }
blockquote.disqualifier {
  margin: 6px 0 2px; padding: 6px 10px; border-left: 3px solid #8a1f1f;
  background: #fdf3f3; font-style: italic;
}
.read-this { margin: 6px 0 0; font-size: 12px; }
.read-this .label { font-weight: bold; text-transform: uppercase; font-size: 11px; }
.muted { color: var(--muted); }
.more { font-style: italic; }
@page { size: __PAGE_SIZE__; margin: 12mm; }
@media print {
  body { padding: 0; }
  .row { break-inside: avoid; page-break-inside: avoid; }
  a { color: inherit; text-decoration: none; }
}
@media (max-width: 640px) {
  h1 { font-size: 19px; }
  .row { padding: 8px; }
}
"""


def _esc(value: Any) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def _settings(config: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    global _ACTIVE_CONFIG
    cfg = config if config is not None else (_ACTIVE_CONFIG or load_config())
    max_rows = cfg_get(cfg, "card.max_rows_per_verdict", 40)
    try:
        max_rows = int(max_rows)
    except (TypeError, ValueError):
        max_rows = 40
    return {
        "page_size": cfg_get(cfg, "card.page_size", "A4") or "A4",
        "output_dir": cfg_get(cfg, "card.output_dir", "results/cards") or "results/cards",
        "max_rows_per_verdict": max_rows,
    }


def _money(value: Any) -> str:
    number = float(value)
    if number.is_integer():
        return f"{int(number):,}"
    return f"{number:,.2f}"


def _award_range(opp: Optional[Opportunity]) -> str:
    if opp is None:
        return "\u2014"
    if opp.award_floor is not None and opp.award_ceiling is not None:
        return f"${_money(opp.award_floor)}\u2013${_money(opp.award_ceiling)}"
    if opp.award_floor is not None:
        return f"from ${_money(opp.award_floor)}"
    if opp.award_ceiling is not None:
        return f"up to ${_money(opp.award_ceiling)}"
    if opp.award_estimate is not None:
        return f"Est. ${_money(opp.award_estimate)}"
    return "\u2014"


def _verdict_of(row: VerdictRow) -> Verdict:
    if isinstance(row.verdict, Verdict):
        return row.verdict
    try:
        return Verdict(row.verdict)
    except ValueError:
        return Verdict.CHECK


def _row_html(row: VerdictRow, opp: Optional[Opportunity]) -> str:
    opp_number = _esc(opp.opp_number if opp else row.opportunity_id)
    title = _esc(opp.title if opp else row.opportunity_id)
    agency = _esc(opp.agency) if opp and opp.agency else "\u2014"
    close = _esc(opp.close_date) if opp and opp.close_date else "\u2014"
    award = _esc(_award_range(opp))
    cost_share = "yes" if opp and opp.cost_sharing else "no/unknown"
    link = opp.link if opp else ""
    link_html = (
        f'<a class="link" href="{_esc(link)}" rel="noopener">{_esc(link)}</a>'
        if link
        else '<span class="muted">\u2014</span>'
    )

    parts = [
        '<div class="row">',
        f'<div class="head"><span class="opp-number">{opp_number}</span> \u2014 {title}</div>',
        f'<div class="facts">Agency: {agency} &middot; Closes: {close} &middot; Award: {award} &middot; Cost share: {_esc(cost_share)}</div>',
        f'<div class="facts">Grants.gov: {link_html}</div>',
    ]

    if _verdict_of(row) == Verdict.NOT_ELIGIBLE:
        quotes = row.disqualifying_quotes or []
        if quotes:
            for quote in quotes:
                parts.append(
                    f'<blockquote class="disqualifier">{_esc(quote)}</blockquote>'
                )
        else:
            parts.append(
                '<p class="muted">No verbatim disqualifying sentence recorded.</p>'
            )
    elif _verdict_of(row) == Verdict.CHECK:
        quotes = row.check_quotes or []
        if quotes:
            for quote in quotes:
                parts.append(
                    f'<p class="read-this"><span class="label">Read:</span> {_esc(quote)}</p>'
                )
        else:
            parts.append('<p class="muted">No sentence to read recorded.</p>')

    parts.append("</div>")
    return "\n".join(parts)


def _section_html(
    title: str,
    rows: list[VerdictRow],
    opp_by_id: dict[str, Opportunity],
    max_rows: int,
) -> str:
    slug = title.lower().replace(" ", "-")
    parts = [
        f'<section class="verdict-section {slug}">',
        f"<h2>{_esc(title)}</h2>",
    ]
    if not rows:
        parts.append('<p class="muted">None.</p>')
    else:
        shown = rows[:max_rows]
        for row in shown:
            parts.append(_row_html(row, opp_by_id.get(row.opportunity_id)))
        remaining = len(rows) - len(shown)
        if remaining > 0:
            parts.append(f'<p class="muted more">&hellip; and {remaining} more</p>')
    parts.append("</section>")
    return "\n".join(parts)


def rows_to_verdictrows(data: Any) -> list[VerdictRow]:
    """Normalise dicts / VerdictRow objects into a list of VerdictRow."""
    if data is None:
        return []
    out: list[VerdictRow] = []
    for item in data:
        if isinstance(item, VerdictRow):
            out.append(item)
            continue
        if not isinstance(item, dict):
            continue
        conditions = [
            Condition.from_dict(c)
            for c in item.get("conditions", []) or []
            if isinstance(c, dict)
        ]
        try:
            verdict = Verdict(item.get("verdict", Verdict.CHECK.value))
        except ValueError:
            verdict = Verdict.CHECK
        out.append(
            VerdictRow(
                opportunity_id=item.get("opportunity_id", ""),
                profile_id=item.get("profile_id", ""),
                verdict=verdict,
                disqualifying_quotes=list(item.get("disqualifying_quotes") or []),
                check_quotes=list(item.get("check_quotes") or []),
                conditions=conditions,
                override=item.get("override"),
            )
        )
    return out


def verdictrows_to_jsonl(rows: Any) -> str:
    """Serialise VerdictRows (or dicts) to JSON Lines text."""
    objs = rows_to_verdictrows(rows)
    if not objs:
        return ""
    return "\n".join(
        json.dumps(row.to_dict(), ensure_ascii=False) for row in objs
    ) + "\n"


def render_card(
    profile: Profile,
    rows: list[VerdictRow],
    opp_by_id: dict[str, Opportunity],
    out_path: str | None = None,
    provenance: Optional[dict[str, Any]] = None,
) -> str:
    """Render one profile's card.

    ``provenance`` is optional for backwards compatibility with the CLI and
    tests. Product cards pass the backend and Grants.gov pull date so a reader
    can tell what produced the result without opening a sidecar file.
    """
    settings = _settings()
    row_objs = rows_to_verdictrows(rows)
    mine = [row for row in row_objs if row.profile_id == profile.id]

    grouped: dict[Verdict, list[VerdictRow]] = {v: [] for v, _ in SECTION_ORDER}
    for row in mine:
        grouped.setdefault(_verdict_of(row), []).append(row)

    sections = [
        _section_html(
            title,
            grouped.get(verdict, []),
            opp_by_id,
            settings["max_rows_per_verdict"],
        )
        for verdict, title in SECTION_ORDER
    ]

    style = _STYLE_TEMPLATE.replace("__PAGE_SIZE__", _esc(settings["page_size"]))
    today = date.today().isoformat()
    provenance = provenance or {}
    backend = str(provenance.get("backend") or "not recorded")
    pull_date = str(provenance.get("pull_date") or "not recorded")
    source_hash = str(provenance.get("source_hash") or "")
    provenance_line = (
        f"Source: Grants.gov &middot; Pulled {_esc(pull_date)} &middot; "
        f"Extraction: {_esc(backend)}"
    )
    if source_hash:
        provenance_line += f" &middot; Source hash: {_esc(source_hash[:12])}"
    doc = (
        '<!DOCTYPE html>\n<html lang="en">\n<head>\n'
        '<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f'<meta name="description" content="{_esc(BRAND)} screening card for {_esc(profile.name)}">\n'
        f"<title>{_esc(BRAND)} \u2014 {_esc(profile.name)}</title>\n"
        f"<style>\n{style}</style>\n</head>\n<body>\n"
        '<div class="card">\n<header>\n'
        f'<div class="brand">{_esc(BRAND)}</div>\n'
        f"<h1>{_esc(profile.name)}</h1>\n"
        f'<div class="meta">Generated {today}</div>\n'
        f'<div class="meta">{provenance_line}</div>\n'
        f'<div class="confirm">{_esc(CONFIRM_LINE)}</div>\n'
        f'<div class="legal">{_esc(LEGAL_NOTE)}</div>\n'
        "</header>\n"
        + "\n".join(sections)
        + "\n</div>\n</body>\n</html>\n"
    )

    if out_path:
        write_text(out_path, doc)
    return doc


def render_all(
    profiles: list[Profile],
    rows_by_profile: dict[str, list[VerdictRow]],
    opp_by_id: dict[str, Opportunity],
    config: dict[str, Any],
    out_dir: str,
    provenance: Optional[dict[str, Any]] = None,
) -> list[str]:
    """Write one HTML card per profile and return the written paths."""
    global _ACTIVE_CONFIG
    settings = _settings(config)
    target_dir = Path(out_dir or settings["output_dir"])
    target_dir.mkdir(parents=True, exist_ok=True)

    previous = _ACTIVE_CONFIG
    _ACTIVE_CONFIG = config
    paths: list[str] = []
    try:
        for profile in profiles:
            target = target_dir / f"{profile.id}.html"
            render_card(
                profile,
                rows_by_profile.get(profile.id, []),
                opp_by_id,
                str(target),
                provenance=provenance,
            )
            paths.append(str(target))
    finally:
        _ACTIVE_CONFIG = previous
    return paths


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m src.cards",
        description="Render printable per-profile verdict cards.",
    )
    parser.add_argument("--profile-id", action="append", default=None, help="only this profile")
    parser.add_argument("--out", default=None, help="output directory")
    parser.add_argument("--profiles", default=None, help="profiles JSON path")
    parser.add_argument("--opportunities", default=None, help="opportunities JSON path")
    parser.add_argument("--rows", default=None, help="verdict rows JSONL path")
    args = parser.parse_args(argv)

    cfg = load_config()
    profiles = load_profiles(
        args.profiles or cfg_get(cfg, "profiles_dir", "data/profiles")
    )
    opp_by_id = {
        opp.id: opp
        for opp in load_opportunities(
            args.opportunities or cfg_get(cfg, "cache.raw_dir", "data/raw")
        )
    }

    if args.profile_id:
        wanted = set(args.profile_id)
        profiles = [p for p in profiles if p.id in wanted]

    rows_by_profile: dict[str, list[VerdictRow]] = {}
    if args.rows and Path(args.rows).exists():
        for line in Path(args.rows).read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                item = json.loads(line)
            except ValueError:
                continue
            row = rows_to_verdictrows([item])[0]
            rows_by_profile.setdefault(row.profile_id, []).append(row)

    out_dir = args.out or cfg_get(cfg, "card.output_dir", "results/cards")
    for path in render_all(profiles, rows_by_profile, opp_by_id, cfg, out_dir):
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
