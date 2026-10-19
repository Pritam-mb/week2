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
from .models import Opportunity, Profile, Verdict, VerdictRow

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
:root {
  --paper: #FAF6EE; --paper-2: #EAE2D0; --ink: #221C14; --ink-soft: #5B5246;
  --rule: #D8CFBD; --rule-dark: #BDB39E;
  --eligible: #4C6B3A; --eligible-bg: #EDF3E8; --eligible-stamp: #3D572E;
  --not: #A93B2B; --not-bg: #FAECE9; --not-stamp: #8A2C1F;
  --check: #C98A12; --check-bg: #FCF5E5; --check-stamp: #9E6B08;
  --highlight: #F7E37A;
}
* { box-sizing: border-box; }
html { overflow-x: hidden; background: var(--paper); color: var(--ink); }
body {
  font-family: "Instrument Sans", -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  color: var(--ink); margin: 0 auto; padding: clamp(16px, 4vw, 32px); line-height: 1.5;
  max-width: 960px; overflow-wrap: anywhere;
}
.card { max-width: 100%; }
header { border-bottom: 2px solid var(--ink); margin-bottom: 24px; padding-bottom: 12px; }
.brand { font-family: "Instrument Sans", sans-serif; font-size: 12px; letter-spacing: 0.05em; text-transform: uppercase; color: var(--ink-soft); font-weight: 600; }
h1 { font-family: "Fraunces", Georgia, serif; font-size: clamp(24px, 4vw, 32px); margin: 6px 0; color: var(--ink); font-weight: 600; line-height: 1.25; text-wrap: balance; }
.meta { font-family: "IBM Plex Mono", monospace; font-size: 12px; color: var(--ink-soft); margin-top: 3px; }
.confirm { font-weight: 600; margin-top: 10px; font-size: 13.5px; }
.legal { font-size: 12px; font-style: italic; color: var(--ink-soft); margin-top: 2px; }
h2 {
  font-family: "Fraunces", Georgia, serif; font-size: 17px; text-transform: uppercase; letter-spacing: 0.05em;
  border-bottom: 2px solid var(--rule); margin: 28px 0 12px; padding-bottom: 4px; font-weight: 600;
}
.verdict-section.not-eligible h2 { color: var(--not); border-color: var(--not); }
.verdict-section.check h2 { color: var(--check-stamp); border-color: var(--check); }
.verdict-section.likely-eligible h2 { color: var(--eligible-stamp); border-color: var(--eligible); }
.row {
  background: #FFFDF9; border: 2px solid var(--ink); border-radius: 3px; padding: 12px 16px;
  margin-bottom: 14px; break-inside: avoid; page-break-inside: avoid;
  box-shadow: 3px 3px 0 var(--ink); position: relative;
}
.row .row-header { display: flex; justify-content: space-between; align-items: flex-start; gap: 12px; }
.row .head { font-family: "Fraunces", Georgia, serif; font-weight: 600; font-size: 16px; flex: 1; line-height: 1.35; color: var(--ink); }
.row .head .opp-number { font-family: "IBM Plex Mono", monospace; font-size: 12.5px; font-weight: 500; color: var(--ink-soft); text-transform: uppercase; }
.row .facts { font-size: 13px; color: var(--ink-soft); margin-top: 6px; }
.link { overflow-wrap: anywhere; word-break: break-word; color: #A8643C; font-family: "IBM Plex Mono", monospace; font-size: 12px; }
.days-chip { font-family: "Instrument Sans", sans-serif; font-size: 12px; font-weight: 500; padding: 2px 6px; border-radius: 2px; background: var(--paper-2); border: 1px solid var(--rule-dark); margin-left: 6px; font-variant-numeric: tabular-nums; }
.days-urgent { background: var(--not-bg); color: var(--not); border-color: var(--not); font-weight: 600; }
.verdict-stamp {
  font-family: "Instrument Sans", sans-serif; font-size: 12px; font-weight: 600; letter-spacing: 0.06em;
  text-transform: uppercase; padding: 4px 10px; border-radius: 2px; border: 2px solid currentColor;
  white-space: nowrap; flex-shrink: 0; box-shadow: 2px 2px 0 var(--ink);
}
.stamp-eligible { color: var(--eligible-stamp); background: var(--eligible-bg); transform: rotate(-2deg); }
.stamp-not { color: var(--not-stamp); background: var(--not-bg); transform: rotate(2.5deg); }
.stamp-check { color: var(--check-stamp); background: var(--check-bg); transform: rotate(-1.5deg); }
blockquote.disqualifier {
  margin: 10px 0 6px; padding: 8px 12px; border-left: 3px solid var(--not);
  background: var(--paper-2); font-style: italic; font-size: 14.5px;
}
.marker-quote {
  background: var(--highlight); color: var(--ink); padding: 1px 4px; border-radius: 2px;
  box-decoration-break: clone; -webkit-box-decoration-break: clone;
}
.read-this { margin: 8px 0 4px; font-size: 14px; }
.read-this .label { font-family: "Instrument Sans", sans-serif; font-weight: 600; text-transform: uppercase; font-size: 12px; letter-spacing: 0.05em; color: var(--check-stamp); }
.source-accordion { margin-top: 8px; border: 1px solid var(--rule); border-radius: 2px; background: var(--paper); }
.source-toggle { padding: 6px 10px; font-family: "Instrument Sans", sans-serif; font-size: 12px; color: #A8643C; cursor: pointer; user-select: none; font-weight: 600; }
.source-content { padding: 8px 10px; font-family: "Fraunces", Georgia, serif; font-size: 13px; line-height: 1.5; color: var(--ink-soft); border-top: 1px solid var(--rule); max-height: 220px; overflow-y: auto; white-space: pre-wrap; }
.btn-flag-wrong { background: transparent; border: 1px dashed var(--rule-dark); font-family: "Instrument Sans", sans-serif; font-size: 12px; padding: 2px 6px; color: var(--ink-soft); cursor: pointer; border-radius: 2px; }
.btn-flag-wrong:hover { border-color: var(--ink); color: var(--not); }
.muted { color: var(--ink-soft); }
.more { font-style: italic; }
@page { size: __PAGE_SIZE__; margin: 12mm; }
@media print {
  body { padding: 0; background: #fff !important; }
  .row { break-inside: avoid; page-break-inside: avoid; box-shadow: none !important; border: 1px solid #666 !important; }
  .source-accordion, .btn-flag-wrong { display: none !important; }
  a { color: inherit; text-decoration: none; }
}
@media (max-width: 640px) {
  h1 { font-size: 21px; }
  .row { padding: 10px; }
  .row .row-header { flex-direction: column-reverse; }
}
"""


def _esc(value: Any) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def _days_left_chip(opp: Optional[Opportunity]) -> str:
    if not opp or not opp.close_date:
        return ""
    try:
        from datetime import date
        text = str(opp.close_date).strip()[:10]
        d = date.fromisoformat(text)
        diff = (d - date.today()).days
        if diff < 0:
            return '<span class="days-chip days-urgent">Closed</span>'
        elif diff == 0:
            return '<span class="days-chip days-urgent">Closes today</span>'
        elif diff <= 7:
            return f'<span class="days-chip days-urgent">{diff}d left</span>'
        else:
            return f'<span class="days-chip">{diff}d left</span>'
    except Exception:
        return ""


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
    days_chip = _days_left_chip(opp)

    v_enum = _verdict_of(row)
    stamp_cls = "stamp-eligible" if v_enum == Verdict.ELIGIBLE else ("stamp-not" if v_enum == Verdict.NOT_ELIGIBLE else "stamp-check")
    stamp_text = "ELIGIBLE" if v_enum == Verdict.ELIGIBLE else ("NOT ELIGIBLE" if v_enum == Verdict.NOT_ELIGIBLE else "CHECK")
    stamp_html = f'<div class="verdict-stamp {stamp_cls}">{stamp_text}</div>'

    flag_btn = (
        f'<button type="button" class="btn-flag-wrong" '
        f'onclick="if(window.flagWrong)flagWrong(\'{_esc(row.opportunity_id)}\')" '
        f'title="Record correction for {opp_number}">&#9873; This is wrong</button>'
    )

    parts = [
        '<div class="row">',
        '<div class="row-header">',
        f'<div class="head"><span class="opp-number">{opp_number}</span> \u2014 {title}</div>',
        stamp_html,
        '</div>',
        f'<div class="facts">Agency: {agency} &middot; Closes: {close} {days_chip} &middot; Award: {award} &middot; Cost share: {_esc(cost_share)}</div>',
        f'<div class="facts">Grants.gov: {link_html} &middot; {flag_btn}</div>',
    ]

    quotes: list[str] = []
    if _verdict_of(row) == Verdict.NOT_ELIGIBLE:
        quotes = row.disqualifying_quotes or []
        if quotes:
            for quote in quotes:
                parts.append(
                    f'<blockquote class="disqualifier"><mark class="marker-quote">{_esc(quote)}</mark></blockquote>'
                )
        else:
            parts.append(
                '<p class="muted">No verbatim disqualifying sentence recorded.</p>'
            )
    elif _verdict_of(row) == Verdict.CHECK:
        reasons = row.check_reasons or [
            "Review the original notice against the profile; no automatic review reason was recorded."
        ]
        for reason in reasons:
            parts.append(
                f'<p class="read-this check-reason"><span class="label">Why CHECK:</span> {_esc(reason)}</p>'
            )
        quotes = row.check_quotes or []
        if quotes:
            for quote in quotes:
                parts.append(
                    f'<p class="read-this"><span class="label">Read:</span> <mark class="marker-quote">{_esc(quote)}</mark></p>'
                )

    if opp and (opp.source_text or opp.eligibility_text) and quotes:
        source_raw = opp.source_text or opp.eligibility_text or ""
        highlighted_snippet = _esc(source_raw)
        for q in quotes:
            if q:
                highlighted_snippet = highlighted_snippet.replace(
                    _esc(q), f'<mark class="marker-quote">{_esc(q)}</mark>'
                )
        parts.append(
            f'<details class="source-accordion"><summary class="source-toggle">Show in source &darr;</summary><div class="source-content">{highlighted_snippet}</div></details>'
        )

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
        out.append(VerdictRow.from_dict(item))
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
