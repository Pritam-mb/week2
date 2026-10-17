"""Tiger Data/PostgreSQL persistence for official Grants.gov snapshots.

The filesystem remains the offline default. Production can set
``GFP_STORAGE=postgres`` and ``DATABASE_URL`` to use Tiger Cloud. This module
stores immutable source revisions and exposes lexical retrieval only; any
retrieved excerpt is discovery data and never replaces the full source text
used by ``verify_conditions``.
"""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from dotenv import load_dotenv

from .models import Opportunity, Profile
from .config import load_config, get
from .io_utils import load_opportunities, load_profiles


SCHEMA = """
CREATE TABLE IF NOT EXISTS opportunity_snapshots (
    snapshot_id BIGSERIAL PRIMARY KEY,
    opportunity_id TEXT NOT NULL,
    opp_number TEXT NOT NULL DEFAULT '',
    title TEXT NOT NULL DEFAULT '',
    agency TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT '',
    open_date TEXT NOT NULL DEFAULT '',
    close_date TEXT NOT NULL DEFAULT '',
    award_floor DOUBLE PRECISION,
    award_ceiling DOUBLE PRECISION,
    award_estimate DOUBLE PRECISION,
    cost_sharing BOOLEAN NOT NULL DEFAULT FALSE,
    applicant_types JSONB NOT NULL DEFAULT '[]'::jsonb,
    synopsis TEXT NOT NULL DEFAULT '',
    eligibility_text TEXT NOT NULL DEFAULT '',
    source_text TEXT NOT NULL DEFAULT '',
    source_hash TEXT NOT NULL,
    link TEXT NOT NULL DEFAULT '',
    raw_payload JSONB,
    captured_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    is_current BOOLEAN NOT NULL DEFAULT TRUE,
    UNIQUE (opportunity_id, source_hash)
);
CREATE UNIQUE INDEX IF NOT EXISTS opportunity_current_idx
    ON opportunity_snapshots(opportunity_id) WHERE is_current;
CREATE INDEX IF NOT EXISTS opportunity_source_hash_idx
    ON opportunity_snapshots(source_hash);
CREATE INDEX IF NOT EXISTS opportunity_search_idx
    ON opportunity_snapshots USING GIN (
        to_tsvector('english', coalesce(title, '') || ' ' || coalesce(agency, '') || ' ' ||
                    coalesce(synopsis, '') || ' ' || coalesce(eligibility_text, ''))
    );
CREATE TABLE IF NOT EXISTS official_link_candidates (
    candidate_id BIGSERIAL PRIMARY KEY,
    opportunity_id TEXT NOT NULL,
    query TEXT NOT NULL,
    url TEXT NOT NULL,
    title TEXT NOT NULL DEFAULT '',
    snippet TEXT NOT NULL DEFAULT '',
    position INTEGER,
    is_official BOOLEAN NOT NULL,
    selected BOOLEAN NOT NULL DEFAULT FALSE,
    discovered_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS official_link_candidate_opp_idx
    ON official_link_candidates(opportunity_id);
CREATE TABLE IF NOT EXISTS client_profiles (
    profile_id TEXT PRIMARY KEY,
    name TEXT NOT NULL DEFAULT '',
    org_type TEXT NOT NULL DEFAULT '',
    us_based BOOLEAN NOT NULL DEFAULT TRUE,
    state TEXT NOT NULL DEFAULT '',
    size_band TEXT NOT NULL DEFAULT '',
    focus_keywords JSONB NOT NULL DEFAULT '[]'::jsonb,
    notes TEXT NOT NULL DEFAULT '',
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS human_corrections (
    correction_key TEXT PRIMARY KEY,
    profile_id TEXT NOT NULL,
    opportunity_id TEXT NOT NULL,
    verdict TEXT NOT NULL,
    note TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS rendered_cards (
    profile_id TEXT PRIMARY KEY,
    card_html TEXT NOT NULL,
    provenance JSONB NOT NULL DEFAULT '{}'::jsonb,
    rendered_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""


@dataclass(frozen=True)
class RetrievalHit:
    opportunity_id: str
    snapshot_id: int
    score: float
    excerpt: str
    official_url: str


def _require_psycopg():
    try:
        import psycopg
        from psycopg.rows import dict_row
    except ImportError as exc:  # pragma: no cover - dependency-gated
        raise RuntimeError(
            "PostgreSQL storage requires psycopg. Run: pip install -e \".[postgres]\""
        ) from exc
    return psycopg, dict_row


class PostgresStore:
    def __init__(self, dsn: str | None = None):
        self.dsn = dsn or os.environ.get("DATABASE_URL")
        if not self.dsn:
            raise RuntimeError("DATABASE_URL is required for Tiger Data storage")

    def connect(self):
        psycopg, dict_row = _require_psycopg()
        return psycopg.connect(self.dsn, row_factory=dict_row)

    def initialize(self) -> None:
        with self.connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(SCHEMA)
            connection.commit()

    def upsert_snapshot(
        self,
        opportunity: Opportunity,
        raw_payload: dict[str, Any] | None = None,
        captured_at: datetime | None = None,
    ) -> int:
        captured_at = captured_at or datetime.now(timezone.utc)
        with self.connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "UPDATE opportunity_snapshots SET is_current = FALSE "
                    "WHERE opportunity_id = %s AND is_current",
                    (opportunity.id,),
                )
                cursor.execute(
                    """INSERT INTO opportunity_snapshots (
                        opportunity_id, opp_number, title, agency, status,
                        open_date, close_date, award_floor, award_ceiling,
                        award_estimate, cost_sharing, applicant_types, synopsis,
                        eligibility_text, source_text, source_hash, link,
                        raw_payload, captured_at, is_current
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                              %s::jsonb, %s, %s, %s, %s, %s, %s::jsonb, %s, TRUE)
                    ON CONFLICT (opportunity_id, source_hash)
                    DO UPDATE SET is_current = TRUE, captured_at = EXCLUDED.captured_at
                    RETURNING snapshot_id""",
                    (
                        opportunity.id,
                        opportunity.opp_number,
                        opportunity.title,
                        opportunity.agency,
                        opportunity.status,
                        opportunity.open_date,
                        opportunity.close_date,
                        opportunity.award_floor,
                        opportunity.award_ceiling,
                        opportunity.award_estimate,
                        opportunity.cost_sharing,
                        json.dumps(opportunity.applicant_types),
                        opportunity.synopsis,
                        opportunity.eligibility_text,
                        opportunity.source_text,
                        opportunity.text_hash,
                        opportunity.link,
                        json.dumps(raw_payload) if raw_payload is not None else "null",
                        captured_at,
                    ),
                )
                snapshot_id = int(cursor.fetchone()["snapshot_id"])
            connection.commit()
        return snapshot_id

    def upsert_snapshots(self, opportunities: list[Opportunity]) -> int:
        """Import a cache in one database connection."""
        with self.connect() as connection:
            with connection.cursor() as cursor:
                # One round trip to retire the old current set, then use
                # psycopg's batched executemany for the remote Tiger service.
                cursor.execute("UPDATE opportunity_snapshots SET is_current = FALSE WHERE is_current")
                statement = """INSERT INTO opportunity_snapshots (
                        opportunity_id, opp_number, title, agency, status,
                        open_date, close_date, award_floor, award_ceiling,
                        award_estimate, cost_sharing, applicant_types, synopsis,
                        eligibility_text, source_text, source_hash, link,
                        raw_payload, is_current
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                              %s::jsonb, %s, %s, %s, %s, %s, NULL, TRUE)
                    ON CONFLICT (opportunity_id, source_hash)
                    DO UPDATE SET is_current = TRUE"""
                params = []
                for opportunity in opportunities:
                    params.append((
                        opportunity.id, opportunity.opp_number, opportunity.title,
                        opportunity.agency, opportunity.status, opportunity.open_date,
                        opportunity.close_date, opportunity.award_floor,
                        opportunity.award_ceiling, opportunity.award_estimate,
                        opportunity.cost_sharing, json.dumps(opportunity.applicant_types),
                        opportunity.synopsis, opportunity.eligibility_text,
                        opportunity.source_text, opportunity.text_hash, opportunity.link,
                    ))
                cursor.executemany(statement, params)
            connection.commit()
        return len(opportunities)

    def current_opportunities(self) -> list[Opportunity]:
        with self.connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """SELECT opportunity_id, opp_number, title, agency, status,
                              open_date, close_date, award_floor, award_ceiling,
                              award_estimate, cost_sharing, applicant_types,
                              synopsis, eligibility_text, link
                       FROM opportunity_snapshots
                       WHERE is_current ORDER BY close_date, title"""
                )
                rows = cursor.fetchall()
        return [_row_to_opportunity(row) for row in rows]

    def search(self, query: str, limit: int = 20, agency: str | None = None) -> list[RetrievalHit]:
        """Return lexical discovery hits; never use these excerpts as evidence."""
        with self.connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """SELECT snapshot_id, opportunity_id, link,
                              ts_rank(to_tsvector('english',
                                coalesce(title, '') || ' ' || coalesce(agency, '') || ' ' ||
                                coalesce(synopsis, '') || ' ' || coalesce(eligibility_text, '')),
                                websearch_to_tsquery('english', %s)) AS score,
                              left(coalesce(synopsis, '') || ' ' || coalesce(eligibility_text, ''), 500)
                       FROM opportunity_snapshots
                       WHERE is_current
                         AND (%s = '' OR agency ILIKE %s)
                         AND (%s = '' OR to_tsvector('english',
                              coalesce(title, '') || ' ' || coalesce(agency, '') || ' ' ||
                              coalesce(synopsis, '') || ' ' || coalesce(eligibility_text, ''))
                              @@ websearch_to_tsquery('english', %s))
                       ORDER BY score DESC, close_date ASC
                       LIMIT %s""",
                    (query, agency or "", f"%{agency}%" if agency else "", query, query, limit),
                )
                rows = cursor.fetchall()
        return [
            RetrievalHit(
                opportunity_id=row["opportunity_id"],
                snapshot_id=int(row["snapshot_id"]),
                score=float(row["score"] or 0),
                excerpt=row["left"],
                official_url=row["link"],
            )
            for row in rows
        ]

    def save_link_candidate(self, candidate: dict[str, Any]) -> None:
        with self.connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """INSERT INTO official_link_candidates
                       (opportunity_id, query, url, title, snippet, position, is_official, selected)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
                    (
                        candidate["opportunity_id"], candidate["query"], candidate["url"],
                        candidate.get("title", ""), candidate.get("snippet", ""),
                        candidate.get("position"), candidate["is_official"],
                        candidate.get("selected", False),
                    ),
                )
            connection.commit()

    def upsert_profile(self, profile: Profile) -> None:
        with self.connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """INSERT INTO client_profiles
                       (profile_id, name, org_type, us_based, state, size_band, focus_keywords, notes, updated_at)
                       VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, %s, now())
                       ON CONFLICT (profile_id) DO UPDATE SET
                         name = EXCLUDED.name,
                         org_type = EXCLUDED.org_type,
                         us_based = EXCLUDED.us_based,
                         state = EXCLUDED.state,
                         size_band = EXCLUDED.size_band,
                         focus_keywords = EXCLUDED.focus_keywords,
                         notes = EXCLUDED.notes,
                         updated_at = EXCLUDED.updated_at""",
                    (
                        profile.id,
                        profile.name,
                        profile.org_type,
                        profile.us_based,
                        profile.state,
                        profile.size_band,
                        json.dumps(profile.focus_keywords),
                        profile.notes,
                    ),
                )
            connection.commit()

    def load_profiles(self) -> list[Profile]:
        with self.connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """SELECT profile_id, name, org_type, us_based, state, size_band, focus_keywords, notes
                       FROM client_profiles ORDER BY name, profile_id"""
                )
                rows = cursor.fetchall()
        profiles: list[Profile] = []
        for r in rows:
            fk = r.get("focus_keywords") or []
            if isinstance(fk, str):
                fk = json.loads(fk)
            profiles.append(
                Profile(
                    id=r["profile_id"],
                    name=r["name"],
                    org_type=r["org_type"],
                    us_based=bool(r["us_based"]),
                    state=r["state"],
                    size_band=r["size_band"],
                    focus_keywords=fk,
                    notes=r["notes"],
                )
            )
        return profiles

    def save_correction(
        self, profile_id: str, opportunity_id: str, verdict: str, note: str = ""
    ) -> dict[str, Any]:
        key = f"{profile_id}|{opportunity_id}"
        now_iso = datetime.now(timezone.utc).isoformat()
        with self.connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """INSERT INTO human_corrections
                       (correction_key, profile_id, opportunity_id, verdict, note, created_at)
                       VALUES (%s, %s, %s, %s, %s, %s)
                       ON CONFLICT (correction_key) DO UPDATE SET
                         verdict = EXCLUDED.verdict,
                         note = EXCLUDED.note,
                         created_at = EXCLUDED.created_at""",
                    (key, profile_id, opportunity_id, verdict, note, now_iso),
                )
            connection.commit()
        return {
            "verdict": verdict,
            "note": note,
            "created_at": now_iso,
            "profile_id": profile_id,
            "opportunity_id": opportunity_id,
        }

    def load_corrections(self) -> dict[str, dict[str, Any]]:
        with self.connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """SELECT correction_key, profile_id, opportunity_id, verdict, note, created_at
                       FROM human_corrections"""
                )
                rows = cursor.fetchall()
        corrections: dict[str, dict[str, Any]] = {}
        for r in rows:
            ca = r["created_at"]
            corrections[r["correction_key"]] = {
                "verdict": r["verdict"],
                "note": r["note"],
                "created_at": ca.isoformat() if hasattr(ca, "isoformat") else str(ca),
                "profile_id": r["profile_id"],
                "opportunity_id": r["opportunity_id"],
            }
        return corrections

    def save_card(
        self, profile_id: str, card_html: str, provenance: dict[str, Any] | None = None
    ) -> None:
        prov = provenance or {}
        with self.connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """INSERT INTO rendered_cards (profile_id, card_html, provenance, rendered_at)
                       VALUES (%s, %s, %s::jsonb, now())
                       ON CONFLICT (profile_id) DO UPDATE SET
                         card_html = EXCLUDED.card_html,
                         provenance = EXCLUDED.provenance,
                         rendered_at = EXCLUDED.rendered_at""",
                    (profile_id, card_html, json.dumps(prov)),
                )
            connection.commit()

    def load_card(self, profile_id: str) -> str | None:
        with self.connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT card_html FROM rendered_cards WHERE profile_id = %s",
                    (profile_id,),
                )
                row = cursor.fetchone()
        return row["card_html"] if row else None


def _row_to_opportunity(row: dict[str, Any]) -> Opportunity:
    applicant_types = row.get("applicant_types") or []
    if isinstance(applicant_types, str):
        applicant_types = json.loads(applicant_types)
    return Opportunity(
        id=row["opportunity_id"],
        opp_number=row["opp_number"],
        title=row["title"],
        agency=row["agency"],
        status=row["status"],
        open_date=row["open_date"],
        close_date=row["close_date"],
        award_floor=row["award_floor"],
        award_ceiling=row["award_ceiling"],
        award_estimate=row["award_estimate"],
        cost_sharing=row["cost_sharing"],
        applicant_types=applicant_types,
        synopsis=row["synopsis"],
        eligibility_text=row["eligibility_text"],
        link=row["link"],
    )


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    parser = argparse.ArgumentParser(prog="python -m src.storage")
    parser.add_argument("command", choices=["init", "import-cache", "search", "sync-profiles"])
    parser.add_argument("--raw-dir", default=None)
    parser.add_argument("--query", default="")
    parser.add_argument("--limit", type=int, default=20)
    args = parser.parse_args(argv)
    store = PostgresStore()
    if args.command == "init":
        store.initialize()
        print("Tiger Data schema initialized.")
    elif args.command == "sync-profiles":
        config = load_config()
        profiles_dir = get(config, "profiles_dir", "data/profiles")
        profiles = load_profiles(profiles_dir)
        for p in profiles:
            store.upsert_profile(p)
        print(f"Synced {len(profiles)} profiles into Tiger Data.")
    elif args.command == "import-cache":
        config = load_config()
        raw_dir = args.raw_dir or get(config, "cache.raw_dir", "data/raw")
        opportunities = load_opportunities(raw_dir)
        store.upsert_snapshots(opportunities)
        print(f"Imported {len(opportunities)} opportunity snapshots from {raw_dir}.")
    elif args.command == "search":
        for hit in store.search(args.query, limit=args.limit):
            print(json.dumps({
                "opportunity_id": hit.opportunity_id,
                "snapshot_id": hit.snapshot_id,
                "score": hit.score,
                "excerpt": hit.excerpt,
                "official_url": hit.official_url,
            }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
