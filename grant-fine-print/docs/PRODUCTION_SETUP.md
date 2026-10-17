# Production setup

This is the real-data path. The offline sample remains available for tests,
but it is never evidence of model quality.

## Configure secrets

Fill `.env` with:

```env
TINKER_API_KEY=...
GFP_PROVIDER_BASE_URL=https://tinker.thinkingmachines.dev/services/tinker-prod/oai/api/v1
GFP_BASE_MODEL=Qwen/Qwen3.5-4B
DATABASE_URL=postgresql://...?...sslmode=require
SERPAPI_KEY=...
```

Create a Tinker key at <https://tinker.thinkingmachines.ai/keys?new_key=true>.
Copy the PostgreSQL connection string from Tiger Cloud. Get a SerpApi key from
<https://serpapi.com/dashboard>. Never place secrets in Git or chat.

## Initialize Tiger Data

```powershell
python -m src.storage init
python -m src.storage import-cache
```

After verifying the import, set:

```env
GFP_STORAGE=postgres
```

The database stores immutable Grants.gov opportunity snapshots. Retrieval
excerpts are discovery data only; the verifier still reads the complete
official snapshot.

## Verify real Tinker inference

Run one opportunity before spending credits on the full cache:

```powershell
python -m src.extract --opportunity data/raw/<id>__<hash>.json --backend prompted --out results/live_extract
```

The config sets Tinker Qwen3.5 `reasoning_effort: false` so structured JSON is
returned in `message.content` rather than spending the output budget on a
reasoning trace. A real run must produce a sidecar whose backend is not
`MockBackend` and whose `offline_fallback` is false.

## Prepare and review SFT data

The candidate builder excludes every opportunity ID in the frozen test CSV:

```powershell
python -m src.train prepare --limit 100
```

Review `data/training/extraction_candidates.jsonl`, checking every assistant
JSON response and quote against its source text. Copy the reviewed file to:

```text
data/training/extraction_reviewed.jsonl
```

The preparation command deliberately does not claim its candidates are
hand-checked.

## Train the Tinker checkpoint

```powershell
pip install -e ".[train]"
python -m src.train train --reviewed data/training/extraction_reviewed.jsonl --epochs 2
```

The command writes the sampler checkpoint path to
`results/tinker_sampler_checkpoint.json` and prints a value like:

```env
GFP_FINE_TUNED_MODEL=tinker://.../sampler_weights/...
```

Use the `sampler_weights` path for inference, not the training-resume
`weights` path.

## Run the real pipeline

```powershell
python -m src.pipeline --systems prompted --cards-from prompted
python -m src.pipeline --systems fine_tuned --cards-from fine_tuned
```

The code-only baseline remains deterministic and does not use Tinker.

## SerpApi boundary

SerpApi is only for finding a missing official Grants.gov URL:

```powershell
python -m src.discovery --id 123 --opportunity-number ABC-123 --title "Example grant"
```

Search snippets never become eligibility evidence and never change a verdict.

## Mastra boundary

Mastra is not in the critical screening path yet. The Python pipeline owns
extraction, quote verification, matching, and corrections. If an agent UI is
added later, Mastra should call typed tools such as `search_opportunities`,
`get_opportunity_snapshot`, and `run_screening`; it must not produce or
override verdicts.

## Before publishing results

1. Confirm prediction sidecars report real backends.
2. Confirm the fine-tuned path is a sampler checkpoint.
3. Confirm frozen labels were committed before model output.
4. Record real latency and provider pricing.
5. Keep SerpApi metadata separate from Grants.gov source text.
6. Use the same Tiger Data URL for the Render web service and scheduled worker.
