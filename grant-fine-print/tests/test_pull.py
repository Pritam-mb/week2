"""Smoke test for the offline (mock) pull path."""

from __future__ import annotations

from pathlib import Path

from src.config import get, load_config
from src.io_utils import load_manifest, opportunity_from_raw, read_json
from src.pull import pull

ROOT = Path(__file__).resolve().parents[1]


def test_pull_mock_smoke(tmp_path: Path) -> None:
    config = load_config(str(ROOT / "config.yaml"))
    config.setdefault("cache", {})["raw_dir"] = str(tmp_path / "raw")
    config["cache"]["manifest"] = str(tmp_path / "raw" / "manifest.json")

    opportunities = pull(config, mock=True)

    # Enough opportunities to exercise the pipeline.
    assert len(opportunities) >= 5

    # The permissive "Others" code must survive mapping.
    assert any("25" in opp.applicant_types for opp in opportunities)

    # The manifest must have been written.
    manifest = load_manifest(config["cache"]["manifest"])
    assert manifest, "manifest.json was not written"
    assert manifest.get("pull_date")
    assert manifest.get("total_pulled", 0) >= len(opportunities)

    # No duplicate text_hash among the cached raw files.
    cached = [
        p
        for p in (tmp_path / "raw").glob("*.json")
        if p.name != "manifest.json"
    ]
    assert cached, "no raw opportunity files were cached"
    hashes = []
    for path in cached:
        raw = read_json(path)
        opp = opportunity_from_raw(raw, get(config, "api.search_fields"))
        hashes.append(opp.text_hash)
    assert len(hashes) == len(set(hashes)), "duplicate text_hash in cached files"
