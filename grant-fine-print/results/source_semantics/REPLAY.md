# Offline matcher replay

Post-hoc diagnostic on **25 notices x 5 constructed profiles = 125 pairs** from the original public evidence bundle.

## Interpretation and limits

- This is a reused development set with single-author labels, not an untouched holdout. Pairs share notices and profiles; they are not independent observations.
- Cached extractions have unverifiable model identity: legacy backend class names do not authenticate a model, checkpoint, prompt, or training run. Replay uses those cached conditions with current quote verification and matching only.
- This is not new inference, a fine-tuning improvement estimate, or a generalization claim. Changes cannot be attributed solely to fine-tuning.
- Only labels' source_text and bundled profiles feed matching; label verdicts and sentences are used only by the canonical evaluator for scoring. No matching rules are fitted to labels. No overrides are applied.
- `code_only` is copied byte-for-byte from original public predictions. `original_*` are also byte-for-byte copies; `replay_*` are separate outputs. Original latency remains historical. Replay latency_ms is null; no inference timing or cost is measured. Evaluation uses an empty metric config.

## Metrics

| System | Accuracy | Missed eligible grants | Human CHECK | Disqualified -> eligible | Automatic accuracy |
|---|---:|---:|---:|---:|---:|
| code_only | 70/125 | 0/33 | 48/125 | 14/65 | 53/77 |
| original_fine_tuned | 29/125 | 2/33 | 101/125 | 0/65 | 12/24 |
| original_prompted | 47/125 | 20/33 | 64/125 | 1/65 | 30/61 |
| replay_fine_tuned | 32/125 | 0/33 | 120/125 | 0/65 | 5/5 |
| replay_prompted | 32/125 | 0/33 | 120/125 | 0/65 | 5/5 |

Full canonical metrics: `eval.json` and `eval_report.html`. `comparison.json` records rate deltas and all verdict changes.

## Offline reproduction

From the project root:

```text
python -B -m src.matcher_replay --bundle results/evidence --legacy-cache data/extract_cache --output results/matcher_replay
python -B -m src.matcher_replay --bundle results/evidence --snapshot results/matcher_replay/conditions_snapshot.json --output results/matcher_replay_snapshot
```

Use a fresh output directory outside existing replay artifacts. Every run also rereads its exported snapshot and compares replay predictions, verifier drop counts and metrics in memory before recording successful snapshot roundtrip verification. Snapshot mode needs only this snapshot, the unchanged evidence bundle, and local Python code; no legacy cache, provider, credentials, config loader, or remote inference is used.

## Hashes and privacy

`conditions_snapshot.json` is keyed by the full SHA256 of whitespace-normalized source text (the historical cache key). Each notice also records the SHA256 of exact UTF-8 source text. Per-system conditions_sha256 hashes compact, sorted-key, UTF-8 JSON of the complete raw condition list before verification. Empty cached lists remain explicit; missing/corrupt entries fail closed.

The snapshot allowlists notice IDs, hashes, system names, and condition type/polarity/value/quote only. Provider URLs, keys, checkpoint metadata, logs, and other cache fields are excluded. `provenance.json` records source and condition hashes, input file hashes, original evidence provenance hash, current code hashes (including match/models/verify), dropped-condition counts, and output hashes. Hashes establish consistency, not external authenticity.
