"""Tests for the corrections override memory."""

from __future__ import annotations

from src.corrections import (
    apply_override,
    corrections_summary,
    load_corrections,
    save_correction,
)


def test_missing_file_returns_empty(tmp_path):
    assert load_corrections(str(tmp_path / "nope.json")) == {}
    assert apply_override({}, "p1", "o1") is None


def test_save_load_apply(tmp_path):
    path = tmp_path / "corrections.json"
    save_correction(str(path), "p1", "o1", "ELIGIBLE", note="ok")

    corrections = load_corrections(str(path))
    assert apply_override(corrections, "p1", "o1") == "ELIGIBLE"
    assert apply_override(corrections, "p1", "missing") is None

    entry = corrections["p1|o1"]
    assert entry["verdict"] == "ELIGIBLE"
    assert entry["note"] == "ok"
    assert entry["created_at"]


def test_save_upserts_same_key(tmp_path):
    path = tmp_path / "corrections.json"
    save_correction(str(path), "p1", "o1", "CHECK")
    save_correction(str(path), "p1", "o1", "ELIGIBLE")
    corrections = load_corrections(str(path))
    assert len(corrections) == 1
    assert apply_override(corrections, "p1", "o1") == "ELIGIBLE"


def test_summary_counts_by_verdict(tmp_path):
    path = tmp_path / "corrections.json"
    save_correction(str(path), "p1", "o1", "ELIGIBLE")
    save_correction(str(path), "p1", "o2", "CHECK")
    save_correction(str(path), "p2", "o1", "ELIGIBLE")
    summary = corrections_summary(load_corrections(str(path)))
    assert summary == {"ELIGIBLE": 2, "CHECK": 1}
