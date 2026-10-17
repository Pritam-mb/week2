"""Tests for SFT training data preparation, dataset construction, and Tinker training workflows."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.models import Opportunity
from src.train import (
    _load_reviewed,
    _test_ids,
    _write_jsonl,
    build_dataset,
    prepare,
    train,
)


def test_test_ids_loader(tmp_path: Path) -> None:
    csv_file = tmp_path / "test.csv"
    csv_file.write_text("opportunity_id,title\n101,Opp 1\n102,Opp 2\n", encoding="utf-8")
    ids = _test_ids(str(csv_file))
    assert ids == {"101", "102"}
    assert _test_ids(str(tmp_path / "nonexistent.csv")) == set()


def test_prepare_rejects_mock_backend() -> None:
    with pytest.raises(ValueError, match="must use a real model; mock is not allowed"):
        prepare({}, "out.jsonl", backend_name="mock")


def test_load_reviewed_validation(tmp_path: Path) -> None:
    empty_file = tmp_path / "empty.jsonl"
    empty_file.write_text("\n\n", encoding="utf-8")
    with pytest.raises(ValueError, match="Reviewed training file is empty"):
        _load_reviewed(str(empty_file))

    bad_json = tmp_path / "bad.jsonl"
    bad_json.write_text("{bad\n", encoding="utf-8")
    with pytest.raises(ValueError, match="Invalid JSON"):
        _load_reviewed(str(bad_json))

    no_assistant = tmp_path / "no_assistant.jsonl"
    no_assistant.write_text(
        json.dumps({"messages": [{"role": "user", "content": "hello"}]}) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="no assistant target"):
        _load_reviewed(str(no_assistant))


def test_train_requires_tinker_api_key(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv("TINKER_API_KEY", raising=False)
    reviewed_file = tmp_path / "reviewed.jsonl"
    reviewed_file.write_text(
        json.dumps(
            {
                "messages": [
                    {"role": "user", "content": "hi"},
                    {"role": "assistant", "content": '{"conditions":[]}'},
                ]
            }
        )
        + "\n",
        encoding="utf-8",
    )
    with pytest.raises(RuntimeError, match="TINKER_API_KEY is required"):
        train({}, str(reviewed_file), "chk.json", epochs=1, rank=8, learning_rate=1e-4)


def test_build_dataset_smoke_test(tmp_path: Path) -> None:
    reviewed_file = tmp_path / "reviewed_smoke.jsonl"
    conversation = {
        "messages": [
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": "Extract conditions."},
            {
                "role": "assistant",
                "content": json.dumps({"conditions": []}),
            },
        ]
    }
    reviewed_file.write_text(json.dumps(conversation) + "\n", encoding="utf-8")

    dataset, clean_path = build_dataset(
        reviewed_path=str(reviewed_file),
        base_model="Qwen/Qwen2.5-3B-Instruct",
        renderer_name="qwen3_5",
        max_length=512,
        batch_size=1,
    )
    assert len(dataset) == 1
    batch = dataset.get_batch(0)
    assert len(batch) == 1
    assert hasattr(batch[0], "model_input")
    assert clean_path.exists()
