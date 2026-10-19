"""End-to-end pipeline: cache -> extract -> verify -> match -> cards.

This is the glue the web app and the CLI both use.

Stage 1 (extract, once per opportunity, cached by text hash) produces raw
conditions. The verifier then drops any condition whose quote is not a
verbatim substring. Stage 2 (match, plain code) compares the verified
conditions with a profile and, per the quote-or-abstain rule, can only emit
NOT ELIGIBLE with a verified quote.

Production model systems require an explicitly configured remote provider. The
deterministic MockBackend remains available only when the caller explicitly
selects ``--backend mock`` or uses the offline demo fixtures.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from typing import Any, Optional

from .baseline import code_only_row
from .cards import render_all
from .config import get, load_config
from .corrections import apply_override, load_corrections
from .extract import extract_conditions, make_backend
from .io_utils import load_manifest, load_opportunities, load_profiles, write_json, write_text
from .match import evaluate_condition, match
from .models import Condition, Opportunity, Profile, VerdictRow
from .verify import verify_conditions


def _load_opportunities(config: dict[str, Any]) -> list[Opportunity]:
    if str(get(config, "storage.backend", "filesystem")).lower() == "postgres":
        from .storage import PostgresStore

        return PostgresStore().current_opportunities()
    return load_opportunities(get(config, "cache.raw_dir"))

DEFAULT_SYSTEMS = ("code_only", "prompted", "fine_tuned")


def _provenance(config: dict[str, Any], backend_used: str) -> dict[str, Any]:
    """Build the small provenance record shown on generated product cards."""
    raw_dir = get(config, "cache.raw_dir") or "data/raw"
    manifest_path = get(config, "cache.manifest") or os.path.join(raw_dir, "manifest.json")
    manifest = load_manifest(manifest_path)
    return {
        "backend": backend_used,
        "pull_date": manifest.get("pull_date") or "not recorded",
    }


def _load_all(
    config: dict[str, Any],
    profile_ids: Optional[list[str]] = None,
) -> tuple[list[Opportunity], list[Profile]]:
    opportunities = _load_opportunities(config)
    profiles = load_profiles(get(config, "profiles_dir"))
    if profile_ids:
        wanted = set(profile_ids)
        profiles = [p for p in profiles if p.id in wanted]
    if not profiles:
        raise RuntimeError(
            f"No profiles found in {get(config, 'profiles_dir')!r}. "
            "Add profile JSON files under data/profiles/."
        )
    return opportunities, profiles


def _has_remote(config: dict[str, Any], backend_name: str = "prompted") -> bool:
    return bool(
        (get(config, "extract.provider_base_url") or os.environ.get("GFP_PROVIDER_BASE_URL"))
        and (os.environ.get("GFP_API_KEY") or os.environ.get("TINKER_API_KEY"))
        and (backend_name != "fine_tuned" or get(config, "extract.fine_tuned_model"))
    )


def run_model_system(
    config: dict[str, Any],
    opportunities: list[Opportunity],
    profiles: list[Profile],
    backend_name: str,
    apply_corrections: bool = False,
) -> tuple[list[VerdictRow], dict[str, int], str]:
    """Run one model-backed system. Returns (rows, dropped_counts, backend_used).

    ``dropped_counts`` maps opportunity id -> number of conditions the
    verifier dropped (missing or non-verbatim quote).
    """
    effective_backend = backend_name
    if backend_name in ("prompted", "fine_tuned") and not _has_remote(config, backend_name):
        raise RuntimeError(
            f"Real {backend_name} inference is not configured. Set TINKER_API_KEY "
            "and GFP_PROVIDER_BASE_URL; fine_tuned also requires GFP_FINE_TUNED_MODEL. "
            "Use --backend mock explicitly for an offline run."
        )

    backend = make_backend(config, effective_backend)
    corrections = (
        load_corrections(get(config, "corrections_path"))
        if apply_corrections
        else {}
    )

    verified_by_opp: dict[str, list[Condition]] = {}
    raw_by_opp: dict[str, list[Condition]] = {}
    dropped_by_opp: dict[str, list[tuple[Condition, str]]] = {}
    latencies: dict[str, float] = {}

    concurrency = int(
        os.environ.get("GFP_CONCURRENCY")
        or get(config, "extract.concurrency", default=8)
    )

    def _extract_worker(opp: Opportunity) -> tuple[str, list[Condition], Any, float]:
        t0 = time.perf_counter()
        try:
            raw = extract_conditions(opp, backend, config)
        except Exception:
            raw = []
        lat = round((time.perf_counter() - t0) * 1000, 3)
        res = verify_conditions(raw, opp.source_text)
        return opp.id, raw, res, lat

    if concurrency > 1 and len(opportunities) > 1 and type(backend).__name__ != "MockBackend":
        from concurrent.futures import ThreadPoolExecutor, as_completed

        with ThreadPoolExecutor(max_workers=concurrency) as executor:
            futures = [executor.submit(_extract_worker, opp) for opp in opportunities]
            for fut in as_completed(futures):
                opp_id, raw, res, lat = fut.result()
                raw_by_opp[opp_id] = raw
                verified_by_opp[opp_id] = res.verified
                dropped_by_opp[opp_id] = res.dropped
                latencies[opp_id] = lat
    else:
        for opp in opportunities:
            opp_id, raw, res, lat = _extract_worker(opp)
            raw_by_opp[opp_id] = raw
            verified_by_opp[opp_id] = res.verified
            dropped_by_opp[opp_id] = res.dropped
            latencies[opp_id] = lat

    rows: list[VerdictRow] = []
    for profile in profiles:
        for opp in opportunities:
            override = apply_override(corrections, profile.id, opp.id)
            row = match(
                verified_by_opp.get(opp.id, []),
                profile,
                opp.id,
                override=override,
                unverified=[cond for cond, _ in dropped_by_opp.get(opp.id, [])],
            )
            row.proposed_disqualifier_quotes = [
                cond.quote
                for cond in raw_by_opp.get(opp.id, [])
                if cond.quote and evaluate_condition(cond, profile) == "conflict"
            ]
            row.latency_ms = latencies.get(opp.id)
            rows.append(row)

    dropped_counts = {
        opp.id: len(dropped_by_opp.get(opp.id, [])) for opp in opportunities
    }
    return rows, dropped_counts, type(backend).__name__


def run(
    config: Optional[dict[str, Any]] = None,
    *,
    profile_ids: Optional[list[str]] = None,
    backend_name: str = "prompted",
    apply_corrections: bool = True,
    write_cards: bool = True,
    out_dir: Optional[str] = None,
    opportunities: Optional[list[Opportunity]] = None,
    discover_links: bool = False,
) -> dict[str, Any]:
    """Product run: one system, all profiles, optional printed cards.

    Returns a dict with ``rows``, ``rows_by_profile``, ``cards``,
    ``n_opportunities``, ``backend_used`` and ``dropped``.
    """
    config = config if config is not None else load_config()
    if opportunities is None:
        opportunities, profiles = _load_all(config, profile_ids)
    else:
        _, profiles = _load_all(config, profile_ids)

    if discover_links or get(config, "pipeline.discover_links", default=False):
        from .discovery import enrich_opportunity_link, is_official_grants_url

        store = None
        if str(get(config, "storage.backend", "filesystem")).lower() == "postgres":
            try:
                from .storage import PostgresStore

                store = PostgresStore()
            except Exception:
                pass
        for opp in opportunities:
            if not opp.link or not is_official_grants_url(opp.link):
                try:
                    enrich_opportunity_link(opp, store=store)
                except Exception:
                    pass

    rows, dropped, backend_used = run_model_system(
        config, opportunities, profiles, backend_name,
        apply_corrections=apply_corrections,
    )

    rows_by_profile: dict[str, list[VerdictRow]] = {}
    for row in rows:
        rows_by_profile.setdefault(row.profile_id, []).append(row)

    opp_by_id = {opp.id: opp for opp in opportunities}
    cards: list[str] = []
    if write_cards:
        out_path = out_dir or get(config, "card.output_dir") or "results/cards"
        cards = render_all(
            profiles,
            rows_by_profile,
            opp_by_id,
            config,
            out_path,
            provenance=_provenance(config, backend_used),
        )

    return {
        "rows": rows,
        "rows_by_profile": rows_by_profile,
        "cards": cards,
        "n_opportunities": len(opportunities),
        "n_profiles": len(profiles),
        "backend_used": backend_used,
        "dropped": dropped,
    }


def run_systems(
    config: Optional[dict[str, Any]] = None,
    systems: tuple[str, ...] = DEFAULT_SYSTEMS,
    write_cards: bool = True,
    cards_from: str = "fine_tuned",
    out_dir: Optional[str] = None,
    opportunity_ids: Optional[set[str]] = None,
    backend_override: Optional[str] = None,
    discover_links: bool = False,
) -> dict[str, Any]:
    """Run the evaluation systems and write one predictions JSONL per system.

    Corrections are NOT applied here: eval compares raw system output.
    ``opportunity_ids`` restricts the run to a labelled test set.
    Returns a dict with ``predictions_files``, ``meta``, ``cards``,
    ``backend_by_system`` and ``dropped``.
    """
    config = config if config is not None else load_config()
    opportunities, profiles = _load_all(config)
    if opportunity_ids is not None:
        opportunities = [o for o in opportunities if o.id in opportunity_ids]

    if discover_links or get(config, "pipeline.discover_links", default=False):
        from .discovery import enrich_opportunity_link, is_official_grants_url

        store = None
        if str(get(config, "storage.backend", "filesystem")).lower() == "postgres":
            try:
                from .storage import PostgresStore

                store = PostgresStore()
            except Exception:
                pass
        for opp in opportunities:
            if not opp.link or not is_official_grants_url(opp.link):
                try:
                    enrich_opportunity_link(opp, store=store)
                except Exception:
                    pass

    pred_dir = get(config, "eval.predictions_dir") or "results/predictions"
    os.makedirs(pred_dir, exist_ok=True)

    predictions_files: dict[str, str] = {}
    meta: dict[str, Any] = {}
    backend_by_system: dict[str, str] = {}
    dropped: dict[str, int] = {}
    rows_by_system: dict[str, list[VerdictRow]] = {}

    for system in systems:
        if system == "code_only":
            rows = [
                code_only_row(opp, profile, config)
                for profile in profiles
                for opp in opportunities
            ]
            backend_used = "none (applicant-type codes only)"
        else:
            rows, system_dropped, backend_used = run_model_system(
                config, opportunities, profiles, backend_override or system,
                apply_corrections=False,
            )
            dropped = system_dropped
        rows_by_system[system] = rows
        backend_by_system[system] = backend_used

        path = os.path.join(pred_dir, f"{system}.jsonl")
        write_text(
            path,
            "".join(
                json.dumps(row.to_dict(), ensure_ascii=False) + "\n"
                for row in rows
            ),
        )
        predictions_files[system] = path
        meta[system] = {
            "backend": backend_used,
            "n_rows": len(rows),
            "offline_fallback": False,
        }
        write_json(os.path.join(pred_dir, f"{system}.meta.json"), meta[system])

    cards: list[str] = []
    if write_cards:
        card_system = cards_from if cards_from in rows_by_system else systems[-1]
        rows = rows_by_system[card_system]
        rows_by_profile: dict[str, list[VerdictRow]] = {}
        for row in rows:
            rows_by_profile.setdefault(row.profile_id, []).append(row)
        opp_by_id = {opp.id: opp for opp in opportunities}
        out_path = out_dir or get(config, "card.output_dir") or "results/cards"
        cards = render_all(
            profiles,
            rows_by_profile,
            opp_by_id,
            config,
            out_path,
            provenance=_provenance(config, backend_by_system[card_system]),
        )

    return {
        "predictions_files": predictions_files,
        "meta": meta,
        "backend_by_system": backend_by_system,
        "cards": cards,
        "dropped": dropped,
        "n_opportunities": len(opportunities),
        "n_profiles": len(profiles),
    }


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m src.pipeline",
        description="Run the Grant Fine Print pipeline.",
    )
    parser.add_argument(
        "--systems",
        default=",".join(DEFAULT_SYSTEMS),
        help="comma-separated systems to run (default: %(default)s)",
    )
    parser.add_argument(
        "--backend",
        default=None,
        help="force a backend for model systems (mock|prompted|fine_tuned)",
    )
    parser.add_argument(
        "--no-cards", action="store_true", help="skip writing printable cards"
    )
    parser.add_argument(
        "--cards-from",
        default="fine_tuned",
        help="which system's rows to render as cards (default: %(default)s)",
    )
    parser.add_argument(
        "--corrections",
        action="store_true",
        help="apply stored corrections (default off for evaluation runs)",
    )
    parser.add_argument(
        "--ids-file",
        default=None,
        help="CSV with an opportunity_id column; restrict the run to those ids",
    )
    parser.add_argument(
        "--discover",
        action="store_true",
        help="Use SerpApi to discover missing official Grants.gov links",
    )
    args = parser.parse_args(argv)

    config = load_config()
    systems = tuple(s.strip() for s in args.systems.split(",") if s.strip())

    opportunity_ids: Optional[set[str]] = None
    if args.ids_file:
        import csv

        with open(args.ids_file, newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            opportunity_ids = {
                (row.get("opportunity_id") or "").strip()
                for row in reader
                if (row.get("opportunity_id") or "").strip()
            }
        print(f"restricting to {len(opportunity_ids)} opportunities from {args.ids_file}")

    if args.corrections and len(systems) == 1:
        result = run(
            config,
            backend_name=args.backend or systems[0],
            write_cards=not args.no_cards,
            discover_links=args.discover,
        )
        print(
            f"ran {result['n_profiles']} profiles x "
            f"{result['n_opportunities']} opportunities "
            f"(backend={result['backend_used']})"
        )
        for card in result["cards"]:
            print(f"card: {card}")
        return 0

    result = run_systems(
        config,
        systems=systems,
        write_cards=not args.no_cards,
        cards_from=args.cards_from,
        opportunity_ids=opportunity_ids,
        backend_override=args.backend,
        discover_links=args.discover,
    )
    for system, path in result["predictions_files"].items():
        print(f"predictions [{system}]: {path}")
        print(f"  backend: {result['backend_by_system'][system]}")
    for card in result["cards"]:
        print(f"card: {card}")
    print("next: python -m src.eval")
    return 0


if __name__ == "__main__":
    sys.exit(main())
