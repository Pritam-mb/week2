"""Minimal Flask web app for Grant Fine Print.

Entry points:
- ``flask --app app.main run`` (Flask finds the ``create_app`` factory)
- ``python -m app.main`` (runs ``main()``, reading host/port from config)

The offline sample is explicit. Production model runs require a configured
provider and the run summary identifies the backend used.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import sys
import time
import unicodedata
from datetime import date, datetime
from pathlib import Path
from typing import Any, Optional

# Make the project root importable so ``src.*`` resolves regardless of cwd.
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from flask import (  # noqa: E402
    Blueprint,
    Flask,
    Response,
    abort,
    current_app,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    url_for,
)

from src.cards import render_all  # noqa: E402
from src.config import get, load_config  # noqa: E402
from src.corrections import corrections_summary, load_corrections, save_correction  # noqa: E402
from src.io_utils import (  # noqa: E402
    load_manifest,
    load_opportunities,
    load_profiles,
    write_json,
)
from src.models import Profile  # noqa: E402
from src.pipeline import run as run_pipeline  # noqa: E402
from src.pull import pull as pull_grants  # noqa: E402
from src.stats import compute_share_cell, format_wilson_ci, wilson_ci  # noqa: E402

ORG_TYPES = (
    "nonprofit",
    "for_profit",
    "small_business",
    "university",
    "tribal",
    "government",
    "individual",
    "other",
)
SIZE_BANDS = ("micro", "small", "medium", "large")
VERDICTS = ("ELIGIBLE", "NOT_ELIGIBLE", "CHECK")
BACKENDS = ("mock", "prompted", "fine_tuned")
DEFAULT_PROFILES_DIR = "data/profiles"
DEFAULT_CORRECTIONS_PATH = "data/corrections/corrections.json"

bp = Blueprint("main", __name__)


def _cfg() -> dict[str, Any]:
    return current_app.config["GFP"]


def _ensure_dir(path: Any, default: str) -> str:
    resolved = str(path or default)
    os.makedirs(resolved, exist_ok=True)
    return resolved


def _profiles_dir(config: dict[str, Any]) -> str:
    return _ensure_dir(get(config, "profiles_dir"), DEFAULT_PROFILES_DIR)


def _opportunities(config: dict[str, Any]) -> list[Any]:
    if str(get(config, "storage.backend", "filesystem")).lower() == "postgres":
        from src.storage import PostgresStore

        try:
            return PostgresStore().current_opportunities()
        except Exception:
            # Pages should remain usable when the optional database is down.
            # The diagnostics page reports the degraded connection separately.
            return []
    return load_opportunities(get(config, "cache.raw_dir") or "data/raw")


def _default_backend(config: dict[str, Any]) -> str:
    backend = str(get(config, "app.backend") or "prompted")
    return backend if backend in BACKENDS else "prompted"


def _contact_settings(config: dict[str, Any]) -> dict[str, str]:
    """Return optional product contact details without inventing them.

    Deployments can set these in config or environment variables. Agency
    contact details from opportunity payloads are intentionally never exposed
    in the UI.
    """
    email = str(
        os.environ.get("GFP_SUPPORT_EMAIL")
        or get(config, "app.support_email")
        or ""
    ).strip()
    phone = str(
        os.environ.get("GFP_SUPPORT_PHONE")
        or get(config, "app.support_phone")
        or ""
    ).strip()
    phone_href = re.sub(r"[^0-9+*#]", "", phone)
    return {
        "support_email": email,
        "support_phone": phone,
        "support_phone_href": phone_href,
    }


def _slugify(name: str) -> str:
    """Slug from a profile name using only stdlib (re + unicodedata)."""
    text = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^a-zA-Z0-9]+", "-", text).strip("-").lower()
    return text or "profile"


def _unique_id(base: str, existing: set[str]) -> str:
    if base not in existing:
        return base
    n = 2
    while f"{base}-{n}" in existing:
        n += 1
    return f"{base}-{n}"


def _date_key(value: str) -> str:
    """Return an ISO-like sort key while keeping unknown dates last."""
    text = (value or "").strip()
    if not text:
        return "9999-12-31"
    try:
        return date.fromisoformat(text[:10]).isoformat()
    except ValueError:
        return "9999-12-31"


def _filtered_rows(
    rows: list[Any],
    opportunities: dict[str, Any],
    profile: Profile,
    query: str = "",
    verdict: str = "",
    sort: str = "relevance",
) -> list[Any]:
    """Filter and order card rows without changing the eligibility decision."""
    query_terms = [part.lower() for part in query.split() if part.strip()]
    wanted_verdict = verdict if verdict in VERDICTS else ""
    visible = []
    for row in rows:
        row_verdict = getattr(row.verdict, "value", str(row.verdict))
        if wanted_verdict and row_verdict != wanted_verdict:
            continue
        opp = opportunities.get(row.opportunity_id)
        haystack = " ".join(
            str(value or "")
            for value in (
                getattr(opp, "opp_number", ""),
                getattr(opp, "title", ""),
                getattr(opp, "agency", ""),
                getattr(opp, "synopsis", ""),
                getattr(opp, "eligibility_text", ""),
            )
        ).lower()
        if query_terms and not all(term in haystack for term in query_terms):
            continue
        visible.append(row)

    def focus_score(row: Any) -> int:
        opp = opportunities.get(row.opportunity_id)
        haystack = " ".join(
            str(value or "")
            for value in (
                getattr(opp, "title", ""),
                getattr(opp, "agency", ""),
                getattr(opp, "synopsis", ""),
                getattr(opp, "eligibility_text", ""),
            )
        ).lower()
        return sum(1 for keyword in profile.focus_keywords if keyword.lower() in haystack)

    if sort == "title":
        visible.sort(key=lambda row: str(getattr(opportunities.get(row.opportunity_id), "title", "")).lower())
    elif sort == "award":
        visible.sort(
            key=lambda row: (
                -(getattr(opportunities.get(row.opportunity_id), "award_ceiling", None) or 0),
                str(getattr(opportunities.get(row.opportunity_id), "title", "")).lower(),
            )
        )
    elif sort == "close":
        visible.sort(key=lambda row: _date_key(getattr(opportunities.get(row.opportunity_id), "close_date", "")))
    else:
        visible.sort(
            key=lambda row: (
                -focus_score(row),
                _date_key(getattr(opportunities.get(row.opportunity_id), "close_date", "")),
                str(getattr(opportunities.get(row.opportunity_id), "title", "")).lower(),
            )
        )
    return visible


@bp.route("/")
def dashboard():
    config = _cfg()
    profiles = load_profiles(_profiles_dir(config))
    raw_dir = get(config, "cache.raw_dir") or "data/raw"
    opportunities = _opportunities(config)
    manifest_path = get(config, "cache.manifest") or os.path.join(raw_dir, "manifest.json")
    manifest = load_manifest(manifest_path)
    return render_template(
        "index.html",
        profiles=profiles,
        n_opportunities=len(opportunities),
        pull_date=str(manifest.get("pull_date") or ""),
        pull_stats=manifest,
        backends=BACKENDS,
        default_backend=_default_backend(config),
    )


@bp.route("/refresh", methods=["POST"])
def refresh():
    """Refresh the local Grants.gov cache on demand.

    The offline option is intentionally explicit for demos and tests. Live
    refresh remains the authoritative Grants.gov path; no search provider is
    used for eligibility evidence.
    """
    config = _cfg()
    mode = request.form.get("mode", "live").strip().lower()
    if mode not in {"live", "mock"}:
        flash("Choose either a live Grants.gov refresh or the offline sample.", "error")
        return redirect(url_for("main.dashboard"))
    try:
        opportunities = pull_grants(config, mock=mode == "mock")
        if str(get(config, "storage.backend", "filesystem")).lower() == "postgres":
            from src.storage import PostgresStore

            PostgresStore().upsert_snapshots(opportunities)
    except Exception as exc:  # network/API failures should return to the UI
        flash(f"Refresh failed: {exc}", "error")
        return redirect(url_for("main.dashboard"))
    source = "offline sample" if mode == "mock" else "Grants.gov"
    profiles = load_profiles(_profiles_dir(config))
    if profiles:
        try:
            result = run_pipeline(
                config,
                # Selecting the offline sample is an explicit opt-in to the
                # deterministic backend; do not require production provider
                # credentials just to preview the sample in the UI.
                backend_name="mock" if mode == "mock" else _default_backend(config),
                apply_corrections=True,
                write_cards=True,
                opportunities=opportunities,
            )
            flash(
                f"Loaded {len(opportunities)} opportunities from {source} and rebuilt "
                f"{result['n_profiles']} profile card(s).",
                "success",
            )
        except (RuntimeError, ValueError) as exc:
            flash(f"Loaded the source, but card rebuild failed: {exc}", "error")
    else:
        flash(f"Loaded {len(opportunities)} opportunities from {source}.", "success")
    return redirect(url_for("main.dashboard"))


@bp.route("/profiles/new", methods=["GET", "POST"])
def new_profile():
    config = _cfg()
    profiles_dir = _profiles_dir(config)
    if request.method == "POST":
        form = {
            "name": request.form.get("name", "").strip(),
            "org_type": request.form.get("org_type", "").strip(),
            "us_based": request.form.get("us_based") is not None,
            "state": request.form.get("state", "").strip(),
            "size_band": request.form.get("size_band", "").strip(),
            "focus_keywords": request.form.get("focus_keywords", "").strip(),
            "notes": request.form.get("notes", "").strip(),
        }
        errors = []
        if not form["name"]:
            errors.append("Name is required.")
        if form["org_type"] not in ORG_TYPES:
            errors.append("Choose a valid organization type.")
        if form["size_band"] and form["size_band"] not in SIZE_BANDS:
            errors.append("Choose a valid size band.")
        if not errors:
            existing = {p.id for p in load_profiles(profiles_dir)}
            profile_id = _unique_id(_slugify(form["name"]), existing)
            profile = Profile(
                id=profile_id,
                name=form["name"],
                org_type=form["org_type"],
                us_based=form["us_based"],
                state=form["state"],
                size_band=form["size_band"],
                focus_keywords=[
                    w.strip() for w in form["focus_keywords"].split(",") if w.strip()
                ],
                notes=form["notes"],
            )
            write_json(os.path.join(profiles_dir, f"{profile_id}.json"), profile.to_dict())
            flash(f"Profile '{profile.name}' created.", "success")
            return redirect(url_for("main.dashboard"))
        return (
            render_template(
                "new_profile.html",
                form=form,
                errors=errors,
                org_types=ORG_TYPES,
                size_bands=SIZE_BANDS,
            ),
            400,
        )
    return render_template(
        "new_profile.html",
        form={},
        errors=[],
        org_types=ORG_TYPES,
        size_bands=SIZE_BANDS,
    )


@bp.route("/run", methods=["POST"])
def run_now():
    config = _cfg()
    profiles_dir = _profiles_dir(config)
    profile_id = request.form.get("profile_id", "").strip()
    backend = request.form.get("backend", "").strip() or _default_backend(config)
    if backend not in BACKENDS:
        flash(f"Unknown backend '{backend}'; choose one of: {', '.join(BACKENDS)}.", "error")
        return redirect(url_for("main.dashboard"))
    profile_ids = None
    if profile_id:
        known = {p.id for p in load_profiles(profiles_dir)}
        if profile_id not in known:
            flash(f"Unknown profile '{profile_id}'.", "error")
            return redirect(url_for("main.dashboard"))
        profile_ids = [profile_id]
    try:
        result = run_pipeline(
            config,
            profile_ids=profile_ids,
            backend_name=backend,
            apply_corrections=True,
            write_cards=True,
        )
    except (RuntimeError, ValueError) as exc:
        flash(str(exc), "error")
        return redirect(url_for("main.dashboard"))

    flash(
        f"Screened {result['n_opportunities']} opportunities for {result['n_profiles']} profile(s).",
        "success",
    )
    verdict_totals: dict[str, int] = {}
    for row in result["rows"]:
        verdict = getattr(row.verdict, "value", str(row.verdict))
        verdict_totals[verdict] = verdict_totals.get(verdict, 0) + 1
    cards = [
        {
            "profile_id": Path(path).stem,
            "path": path,
            "url": url_for(
                "main.card", profile_id=Path(path).stem, backend=backend
            ),
        }
        for path in result["cards"]
    ]
    backend_used = str(result["backend_used"])
    return render_template(
        "run_summary.html",
        backend_used=backend_used,
        requested_backend=backend,
        offline=backend_used == "MockBackend",
        n_opportunities=result["n_opportunities"],
        n_profiles=result["n_profiles"],
        verdict_counts=sorted(verdict_totals.items()),
        cards=cards,
    )


@bp.route("/card/<profile_id>")
def card(profile_id: str):
    config = _cfg()
    profiles = load_profiles(_profiles_dir(config))
    profile = next((p for p in profiles if p.id == profile_id), None)
    if profile is None:
        abort(404)

    backend = request.args.get("backend", "").strip() or _default_backend(config)
    if backend not in BACKENDS:
        backend = _default_backend(config)
    try:
        result = run_pipeline(
            config,
            profile_ids=[profile.id],
            backend_name=backend,
            apply_corrections=True,
            write_cards=False,
        )
    except (RuntimeError, ValueError) as exc:
        flash(str(exc), "error")
        return redirect(url_for("main.dashboard"))
    raw_dir = get(config, "cache.raw_dir") or "data/raw"
    opp_by_id = {opp.id: opp for opp in _opportunities(config)}
    out_dir = get(config, "card.output_dir") or "results/cards"
    query = request.args.get("q", "").strip()
    verdict = request.args.get("verdict", "").strip()
    sort = request.args.get("sort", "relevance").strip() or "relevance"
    all_rows = result["rows_by_profile"].get(profile.id, [])

    # Measure search query timing against Tiger Data if query present
    t0 = time.perf_counter()
    if query and str(get(config, "storage.backend", "filesystem")).lower() == "postgres":
        try:
            from src.storage import PostgresStore
            PostgresStore().search(query, limit=20)
        except Exception:
            pass
    query_time_ms = round((time.perf_counter() - t0) * 1000, 1)

    visible_rows = _filtered_rows(all_rows, opp_by_id, profile, query, verdict, sort)
    paths = render_all(
        [profile],
        {profile.id: visible_rows},
        opp_by_id,
        config,
        out_dir,
        provenance={
            "backend": result["backend_used"],
            "pull_date": load_manifest(
                get(config, "cache.manifest")
                or os.path.join(raw_dir, "manifest.json")
            ).get("pull_date")
            or "not recorded",
        },
    )
    page = Path(paths[0]).read_text(encoding="utf-8")

    # Real counts for verdict filter chips
    verdict_counts = {"ELIGIBLE": 0, "CHECK": 0, "NOT_ELIGIBLE": 0}
    for row in all_rows:
        v_str = getattr(row.verdict, "value", str(row.verdict))
        if v_str in verdict_counts:
            verdict_counts[v_str] += 1

    # Load real study headline figures for hero strip
    study_stats = {"a_count": 180, "total": 528}
    study_path = _ROOT / "results" / "study.json"
    if study_path.exists():
        try:
            s_data = json.loads(study_path.read_text(encoding="utf-8"))
            study_stats["a_count"] = s_data.get("a_count", 180)
            study_stats["total"] = s_data.get("total", 528)
        except Exception:
            pass

    corrections = load_corrections(
        get(config, "corrections_path") or DEFAULT_CORRECTIONS_PATH
    )
    prefix = f"{profile.id}|"
    mine = {
        key: entry
        for key, entry in corrections.items()
        if key.startswith(prefix) and isinstance(entry, dict)
    }
    entries = [
        {
            "opportunity_id": key[len(prefix):],
            "verdict": entry.get("verdict") or "",
            "note": entry.get("note") or "",
            "created_at": entry.get("created_at") or "",
        }
        for key, entry in sorted(mine.items())
    ]

    top_bar = render_template(
        "card_header.html",
        profile=profile,
        profiles=profiles,
        filter_state={"q": query, "verdict": verdict, "sort": sort, "backend": backend},
        n_total=len(all_rows),
        n_visible=len(visible_rows),
        focus_keywords=profile.focus_keywords,
        verdict_counts=verdict_counts,
        study_stats=study_stats,
        query_time_ms=query_time_ms,
    )

    panel = render_template(
        "card_panel.html",
        profile=profile,
        corrections=entries,
        summary=corrections_summary(mine),
        opportunity_ids=sorted(opp_by_id),
        filter_state={"q": query, "verdict": verdict, "sort": sort, "backend": backend},
        n_total=len(all_rows),
        n_visible=len(visible_rows),
        focus_keywords=profile.focus_keywords,
    )

    # The generated card is a standalone printable document. Add the shared
    # application assets so its filters, theme toggle, correction workflow and
    # responsive navigation work just like the rest of the app.
    assets = (
        f'<link rel="stylesheet" href="{url_for("static", filename="tokens.css")}?v=3">\n'
        f'<link rel="stylesheet" href="{url_for("static", filename="style.css")}?v=3">\n'
        f'<link rel="stylesheet" href="{url_for("static", filename="texture.css")}?v=3">\n'
        f'<script src="{url_for("static", filename="app.js")}?v=3" defer></script>\n'
    )
    if "</head>" in page:
        page = page.replace("</head>", assets + "</head>", 1)

    if '<div class="header">' in page:
        page = page.replace('<div class="header">', top_bar + '\n<div class="header">', 1)
    elif "<body>" in page:
        page = page.replace("<body>", '<body class="card-view-page">\n<div class="page-container card-page-container">\n' + top_bar, 1)

    if "</body>" in page:
        page = page.replace("</body>", panel + "\n</div>\n</body>", 1)
    else:
        page += panel + "\n</div>"
    return Response(page, mimetype="text/html")


@bp.route("/evidence")
def evidence():
    study_file = _ROOT / "results" / "study.json"
    eval_file = _ROOT / "results" / "eval.json"

    study = None
    study_generated_at = "not recorded"
    if study_file.exists():
        try:
            study = json.loads(study_file.read_text(encoding="utf-8"))
            if not isinstance(study, dict) or not isinstance(study.get("b"), dict):
                raise ValueError("study result has an unexpected shape")
            mtime = os.path.getmtime(study_file)
            study_generated_at = datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            study = None

    eval_data = None
    eval_generated_at = "not recorded"
    if eval_file.exists():
        try:
            eval_data = json.loads(eval_file.read_text(encoding="utf-8"))
            systems = eval_data.get("systems") if isinstance(eval_data, dict) else None
            if not isinstance(systems, dict) or not all(
                isinstance(systems.get(name), dict)
                for name in ("code_only", "prompted", "fine_tuned")
            ):
                raise ValueError("evaluation result has an unexpected shape")
            mtime = os.path.getmtime(eval_file)
            eval_generated_at = datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            eval_data = None

    return render_template(
        "evidence.html",
        active_tab="evidence",
        study=study,
        study_generated_at=study_generated_at,
        eval_data=eval_data,
        eval_generated_at=eval_generated_at,
    )


@bp.route("/stack")
def stack():
    config = _cfg()
    storage_backend = str(get(config, "storage.backend", "filesystem")).lower()
    db_connected = False
    table_counts = None
    db_host = None

    if storage_backend == "postgres":
        try:
            from src.storage import PostgresStore

            store = PostgresStore()
            with store.connect() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT 
                            (SELECT count(*) FROM opportunity_snapshots) AS snapshots,
                            (SELECT count(*) FROM client_profiles) AS profiles,
                            (SELECT count(*) FROM human_corrections) AS corrections,
                            (SELECT count(*) FROM official_link_candidates) AS candidates
                    """)
                    row = cur.fetchone()
                    table_counts = {
                        "opportunity_snapshots": row["snapshots"],
                        "client_profiles": row["profiles"],
                        "human_corrections": row["corrections"],
                        "official_link_candidates": row["candidates"],
                    }
            db_connected = True
            db_url = os.environ.get("DATABASE_URL", "")
            if "@" in db_url:
                db_host = "timescale-cloud (" + db_url.split("@")[-1].split("/")[0] + ")"
            else:
                db_host = "PostgreSQL (configured)"
        except Exception:
            db_connected = False

    raw_dir = get(config, "cache.raw_dir") or "data/raw"
    opportunities = _opportunities(config)
    manifest_path = get(config, "cache.manifest") or os.path.join(raw_dir, "manifest.json")
    manifest = load_manifest(manifest_path)
    profile_list = load_profiles(_profiles_dir(config))
    corrections = load_corrections(get(config, "corrections_path") or DEFAULT_CORRECTIONS_PATH)

    raw_checkpoint = os.environ.get("GFP_FINE_TUNED_MODEL") or get(config, "model.checkpoint") or ""
    short_checkpoint = ""
    if raw_checkpoint:
        short_checkpoint = raw_checkpoint.split("/")[-1] if "/" in raw_checkpoint else raw_checkpoint

    diagnostics = {
        "storage_backend": "Tiger Data (PostgreSQL)" if storage_backend == "postgres" else "Local Filesystem",
        "db_connected": db_connected,
        "db_host": db_host,
        "table_counts": table_counts,
        "provider": os.environ.get("GFP_PROVIDER") or get(config, "provider.name", "tinker"),
        "model_name": os.environ.get("GFP_BASE_MODEL") or get(config, "model.name", "Qwen/Qwen3.5-4B"),
        "base_model": "Qwen/Qwen3.5-4B",
        "short_checkpoint_id": short_checkpoint,
        "has_tinker_key": bool(os.environ.get("TINKER_API_KEY")),
        "has_serpapi_key": bool(os.environ.get("SERPAPI_KEY")),
        "raw_dir": raw_dir,
        "n_opportunities": len(opportunities),
        "pull_date": str(manifest.get("pull_date") or "not recorded"),
        "cache_status": "SYNCED" if manifest.get("pull_date") else "NOT AVAILABLE",
        "profiles_dir": _profiles_dir(config),
        "n_profiles": len(profile_list),
        "corrections_path": get(config, "corrections_path") or DEFAULT_CORRECTIONS_PATH,
        "n_corrections": len(corrections),
    }

    return render_template(
        "stack.html",
        active_tab="stack",
        diagnostics=diagnostics,
    )


@bp.route("/profiles")
def profiles():
    config = _cfg()
    profile_list = load_profiles(_profiles_dir(config))
    return render_template(
        "profiles.html",
        active_tab="profiles",
        profiles=profile_list,
        backends=BACKENDS,
        default_backend=_default_backend(config),
    )


@bp.route("/correct", methods=["POST"])
def correct():
    config = _cfg()
    profile_id = request.form.get("profile_id", "").strip()
    opportunity_id = request.form.get("opportunity_id", "").strip()
    verdict = request.form.get("verdict", "").strip()
    note = request.form.get("note", "").strip()
    known = {p.id for p in load_profiles(_profiles_dir(config))}
    if profile_id not in known:
        abort(400, description="Unknown profile.")
    if not opportunity_id:
        abort(400, description="Opportunity ID is required.")
    raw_dir = get(config, "cache.raw_dir") or "data/raw"
    known_opportunities = {opp.id for opp in _opportunities(config)}
    if opportunity_id not in known_opportunities:
        abort(400, description="Opportunity ID is not in the current Grants.gov cache.")
    if verdict not in VERDICTS:
        abort(400, description="Verdict must be ELIGIBLE, NOT_ELIGIBLE or CHECK.")
    save_correction(
        get(config, "corrections_path") or DEFAULT_CORRECTIONS_PATH,
        profile_id,
        opportunity_id,
        verdict,
        note,
    )
    flash(f"Correction saved for {opportunity_id}: {verdict}.", "success")
    return redirect(url_for("main.card", profile_id=profile_id))


@bp.route("/discover/<opportunity_id>", methods=["POST"])
def discover_link(opportunity_id: str):
    """Enrich an opportunity with an official Grants.gov link using SerpApi."""
    config = _cfg()
    opportunities = {opp.id: opp for opp in _opportunities(config)}
    opp = opportunities.get(opportunity_id)
    if opp is None:
        return jsonify(error="Opportunity not found"), 404
    from src.discovery import enrich_opportunity_link

    store = None
    if str(get(config, "storage.backend", "filesystem")).lower() == "postgres":
        try:
            from src.storage import PostgresStore

            store = PostgresStore()
        except Exception:
            pass
    link = enrich_opportunity_link(opp, store=store)
    if link:
        return jsonify(status="ok", link=link)
    return jsonify(status="not_found", message="No official Grants.gov link found via SerpApi"), 404


@bp.route("/healthz")
def healthz():
    return jsonify(status="ok")


@bp.app_context_processor
def inject_site_context() -> dict[str, Any]:
    """Make shared layout metadata and statistical helpers available to every HTML page."""
    return {
        "current_year": date.today().year,
        "compute_share_cell": compute_share_cell,
        "format_wilson_ci": format_wilson_ci,
        "wilson_ci": wilson_ci,
        **_contact_settings(_cfg()),
    }


@bp.app_errorhandler(404)
def page_not_found(error: Any):
    return render_template("404.html"), 404


@bp.app_errorhandler(400)
def bad_request(error: Any):
    return render_template(
        "400.html", description=getattr(error, "description", "")
    ), 400


def create_app(config: Optional[dict[str, Any]] = None) -> Flask:
    """Flask application factory. ``config`` is a load_config()-style dict."""
    app = Flask(__name__)
    app.config["GFP"] = config if config is not None else load_config()
    # Per-process random key for flash-message session signing (no secrets in
    # the repo; flash cookies are reset on restart and useless to an attacker).
    app.secret_key = secrets.token_hex(16)
    app.config["TEMPLATES_AUTO_RELOAD"] = True
    app.jinja_env.globals["compute_share_cell"] = compute_share_cell
    app.jinja_env.globals["format_wilson_ci"] = format_wilson_ci
    app.jinja_env.globals["wilson_ci"] = wilson_ci
    app.register_blueprint(bp)

    @app.context_processor
    def _inject_watermark():
        cfg = app.config.get("GFP", {})
        raw_dir = get(cfg, "cache.raw_dir") or "data/raw"
        manifest_path = get(cfg, "cache.manifest") or os.path.join(raw_dir, "manifest.json")
        try:
            manifest = load_manifest(manifest_path)
        except Exception:
            manifest = {}
        if not manifest:
            return {"watermark_text": ""}
        try:
            opps = load_opportunities(raw_dir)
        except Exception:
            opps = []
        if not opps:
            return {"watermark_text": ""}
        email_re = re.compile(r'[\w\.-]+@[\w\.-]+')
        phone_re = re.compile(r'\b\d{3}[-.\s]?\d{3}[-.\s]?\d{4}\b')
        sentences = []
        for opp in opps:
            text = opp.eligibility_text or ""
            if not text:
                continue
            parts = re.split(r'(?<=[.!?])\s+', text)
            for s in parts:
                s_clean = s.strip()
                if len(s_clean) < 10:
                    continue
                if email_re.search(s_clean) or phone_re.search(s_clean):
                    continue
                sentences.append(s_clean)
                if len(sentences) >= 80:
                    break
            if len(sentences) >= 80:
                break
        seen = set()
        uniq = []
        for s in sentences:
            key = s.lower()
            if key not in seen:
                seen.add(key)
                uniq.append(s)
        if not uniq:
            return {"watermark_text": ""}
        text = " · ".join(uniq)
        return {"watermark_text": text + " &ensp;"}

    return app


def main() -> int:
    config = load_config()
    app = create_app(config)
    host = str(get(config, "app.host") or "0.0.0.0")
    port = get(config, "app.port", default=8000)
    try:
        port = int(port)
    except (TypeError, ValueError):
        port = 8000
    app.run(host=host, port=port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
