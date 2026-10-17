"""Prepare extraction SFT data and train a real Tinker LoRA checkpoint.

The test set is never used for training. ``prepare`` writes model-assisted
candidate examples from opportunities outside the frozen test IDs. A human
must copy that file to the reviewed path and check the assistant JSON/quotes
before ``train`` will submit data to Tinker.

Examples:

    python -m src.train prepare
    # review data/training/extraction_candidates.jsonl and copy it to
    # data/training/extraction_reviewed.jsonl
    python -m src.train train --epochs 2
"""

from __future__ import annotations

import argparse
import csv
import json
import os
from pathlib import Path
from typing import Any

from .config import get, load_config
from .extract import EXTRACTION_SYSTEM, _build_prompt, extract_conditions, make_backend
from .io_utils import load_opportunities, write_json


DEFAULT_CANDIDATES = "data/training/extraction_candidates.jsonl"
DEFAULT_REVIEWED = "data/training/extraction_reviewed.jsonl"
DEFAULT_CHECKPOINT = "results/tinker_sampler_checkpoint.json"


def _test_ids(path: str) -> set[str]:
    ids: set[str] = set()
    if not Path(path).exists():
        return ids
    with Path(path).open("r", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            if row.get("opportunity_id"):
                ids.add(row["opportunity_id"].strip())
    return ids


def _write_jsonl(path: str, rows: list[dict[str, Any]]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )


def prepare(
    config: dict[str, Any],
    output: str,
    limit: int | None = None,
    backend_name: str = "prompted",
) -> int:
    """Create model-assisted candidate SFT conversations from non-test data."""
    opportunities = load_opportunities(get(config, "cache.raw_dir", "data/raw"))
    test_ids = _test_ids(get(config, "eval.labels_path", "data/labels/test_labels.csv"))
    selected = [opp for opp in opportunities if opp.id not in test_ids]
    if limit is not None:
        selected = selected[:limit]

    if backend_name == "mock":
        raise ValueError("Training candidates must use a real model; mock is not allowed")
    backend = make_backend(config, backend_name)
    rows: list[dict[str, Any]] = []
    for opportunity in selected:
        conditions = extract_conditions(opportunity, backend, config)
        prompt = _build_prompt(opportunity)
        rows.append(
            {
                "messages": [
                    {"role": "system", "content": EXTRACTION_SYSTEM},
                    {"role": "user", "content": prompt},
                    {
                        "role": "assistant",
                        "content": json.dumps(
                            {"conditions": [c.to_dict() for c in conditions]},
                            ensure_ascii=False,
                        ),
                    },
                ],
                "metadata": {
                    "opportunity_id": opportunity.id,
                    "source_hash": opportunity.text_hash,
                    "review_required": True,
                },
            }
        )
    _write_jsonl(output, rows)
    print(f"Wrote {len(rows)} candidate conversations to {output}")
    print("Review every assistant response and verbatim quote before training.")
    return 0


def _load_reviewed(path: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with Path(path).open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSON on line {line_number} of {path}: {exc}") from exc
            messages = row.get("messages") if isinstance(row, dict) else None
            if not isinstance(messages, list) or not any(
                message.get("role") == "assistant" for message in messages if isinstance(message, dict)
            ):
                raise ValueError(f"Line {line_number} of {path} has no assistant target")
            rows.append({"messages": messages})
    if not rows:
        raise ValueError(f"Reviewed training file is empty: {path}")
    return rows


def _patch_blobfile_windows() -> None:
    """Ensure blobfile recognizes Windows drive paths (e.g. C:\\ or D:\\) as local."""
    if os.name != "nt":
        return
    try:
        import urllib.parse
        import blobfile._context

        orig_is_local = blobfile._context._is_local_path

        def patched_is_local_path(path: str) -> bool:
            url = urllib.parse.urlparse(path)
            if len(url.scheme) == 1 and url.scheme.isalpha():
                return True
            return orig_is_local(path)

        blobfile._context._is_local_path = patched_is_local_path
    except (ImportError, AttributeError):
        pass


def build_dataset(
    reviewed_path: str,
    base_model: str,
    renderer_name: str = "qwen3_5",
    max_length: int = 4096,
    batch_size: int = 2,
) -> tuple[Any, Path]:
    """Construct a tokenized train dataset from reviewed conversations."""
    _patch_blobfile_windows()
    rows = _load_reviewed(reviewed_path)
    clean_path = Path(reviewed_path).with_suffix(".clean.jsonl")
    _write_jsonl(str(clean_path), rows)

    try:
        import importlib
        importlib.import_module(f"tinker_cookbook.renderers.{renderer_name}")
    except ImportError:
        pass

    try:
        from tinker_cookbook.renderers import TrainOnWhat
        from tinker_cookbook.supervised import (
            ChatDatasetBuilderCommonConfig,
            FromConversationFileBuilder,
        )
    except ImportError as exc:
        raise RuntimeError(
            "Training requires optional packages: pip install tinker tinker-cookbook"
        ) from exc

    builder = FromConversationFileBuilder(
        file_path=str(clean_path),
        test_size=0,
        common_config=ChatDatasetBuilderCommonConfig(
            model_name_for_tokenizer=base_model,
            renderer_name=renderer_name,
            max_length=max_length,
            batch_size=batch_size,
            train_on_what=TrainOnWhat.LAST_ASSISTANT_MESSAGE,
        ),
    )
    train_dataset, _ = builder()
    return train_dataset, clean_path


def train(
    config: dict[str, Any],
    reviewed_path: str,
    checkpoint_path: str,
    epochs: int,
    rank: int,
    learning_rate: float,
) -> int:
    """Run supervised LoRA training using the official Tinker SDK."""
    if not os.environ.get("TINKER_API_KEY"):
        raise RuntimeError("TINKER_API_KEY is required for training")
    try:
        import tinker
        from tinker import types
    except ImportError as exc:
        raise RuntimeError(
            "Training requires the optional packages. Run: "
            "pip install -e \".[train]\""
        ) from exc

    base_model = str(get(config, "extract.base_model") or os.environ.get("GFP_BASE_MODEL") or "")
    if not base_model:
        raise RuntimeError("Set GFP_BASE_MODEL or extract.base_model before training")

    renderer_name = str(get(config, "training.renderer", "qwen3_5"))
    max_length = int(get(config, "training.max_length", 4096))
    batch_size = int(get(config, "training.batch_size", 2))

    train_dataset, _ = build_dataset(
        reviewed_path=reviewed_path,
        base_model=base_model,
        renderer_name=renderer_name,
        max_length=max_length,
        batch_size=batch_size,
    )

    service_client = tinker.ServiceClient(display_name="grant-fine-print-sft")
    training_client = service_client.create_lora_training_client(
        base_model=base_model,
        rank=rank,
    )

    for epoch in range(epochs):
        train_dataset.set_epoch(epoch)
        for batch_index in range(len(train_dataset)):
            batch = train_dataset.get_batch(batch_index)
            forward_future = training_client.forward_backward(batch, "cross_entropy")
            optim_future = training_client.optim_step(
                adam_params=types.AdamParams(learning_rate=learning_rate)
            )
            forward_result = forward_future.result()
            optim_future.result()
            loss = "recorded"
            if hasattr(forward_result, "metrics") and isinstance(forward_result.metrics, dict):
                loss = forward_result.metrics.get("loss", loss)
            elif hasattr(forward_result, "loss"):
                loss = forward_result.loss
            print(f"epoch={epoch + 1} batch={batch_index + 1} loss={loss}")

    checkpoint = training_client.save_weights_for_sampler(
        name=str(get(config, "training.checkpoint_name", "grant-fine-print-sft")),
    ).result()
    result = {
        "checkpoint_path": checkpoint.path,
        "base_model": base_model,
        "training_file": reviewed_path,
        "epochs": epochs,
        "rank": rank,
        "learning_rate": learning_rate,
    }
    write_json(checkpoint_path, result)
    print(f"Saved sampler checkpoint path to {checkpoint_path}")
    print(f"GFP_FINE_TUNED_MODEL={checkpoint.path}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m src.train")
    subparsers = parser.add_subparsers(dest="command", required=True)
    prepare_parser = subparsers.add_parser("prepare")
    prepare_parser.add_argument("--out", default=DEFAULT_CANDIDATES)
    prepare_parser.add_argument("--limit", type=int, default=None)
    prepare_parser.add_argument("--backend", choices=["prompted"], default="prompted")
    train_parser = subparsers.add_parser("train")
    train_parser.add_argument("--reviewed", default=DEFAULT_REVIEWED)
    train_parser.add_argument("--checkpoint-out", default=DEFAULT_CHECKPOINT)
    train_parser.add_argument("--epochs", type=int, default=2)
    train_parser.add_argument("--rank", type=int, default=16)
    train_parser.add_argument("--learning-rate", type=float, default=2e-4)
    args = parser.parse_args(argv)
    config = load_config()
    if args.command == "prepare":
        return prepare(config, args.out, args.limit, args.backend)
    return train(
        config,
        args.reviewed,
        args.checkpoint_out,
        args.epochs,
        args.rank,
        args.learning_rate,
    )


if __name__ == "__main__":
    raise SystemExit(main())
