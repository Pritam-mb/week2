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

from .models import Opportunity
from .config import load_config, get
from .io_utils import load_opportunities


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
    parser.add_argument("command", choices=["init", "import-cache", "search"])
    parser.add_argument("--raw-dir", default=None)
    parser.add_argument("--query", default="")
    parser.add_argument("--limit", type=int, default=20)
    args = parser.parse_args(argv)
    store = PostgresStore()
    if args.command == "init":
        store.initialize()
        print("Tiger Data schema initialized.")
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
