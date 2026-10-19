# Offline demo and evidence verification

Run commands from `grant-fine-print/`, with Python 3.10+.

## Verify real saved outputs (no keys, no packages, no provider calls)

```powershell
python -B -S -m src.evidence_bundle verify --bundle results/evidence
```

This recomputes scores and worked examples from saved predictions, checks hashes,
and enforces exact pair coverage. **It does not rerun model inference.** The
25-notice, five-profile benchmark has single-author labels and diagnostic reuse.

To replay the current verifier/matcher from public historical condition snapshots:

```powershell
python -B -S -m src.matcher_replay --bundle results/evidence --snapshot results/source_semantics/conditions_snapshot.json --output results/matcher_replay_check
```

Choose a fresh output folder for each run. See `results/source_semantics/REPLAY.md`
for limitations. Never present this post-hoc replay as a new fine-tune or holdout.

Open `reports/proof_pack/index.html` directly in a browser for a self-contained
comparison of actual saved baseline misses and an honest CHECK case. This is
explicitly labelled offline development evidence, not live model inference.

## Exercise the product plumbing safely

With the project test dependencies installed:

```powershell
# PowerShell: prevent local deployment credentials from entering test setup.
$env:PYTHON_DOTENV_DISABLED = '1'
python -B -m pytest -q -p no:cacheprovider tests/test_app.py tests/test_cards.py tests/test_review_reasons.py
```

These tests use temporary paths and explicit mock backends to exercise profile
creation, printable cards, source excerpts, CHECK explanations, filters, and
corrections. They do not provide a real-model accuracy estimate.

For interactive UI exploration, use a separate checkout with no private `.env`,
filesystem storage, and the `mock` backend selected explicitly. Run
`python -m app.main`, open `http://127.0.0.1:8000`, and load the offline sample.
That sample is synthetic; label screenshots and metrics accordingly.

## Protect the evidence

- Do not run `src.study` on mock/mixed raw caches and overwrite the historical audit.
- Do not overwrite original prediction files with mock outputs and then call their
  scores real-model performance. Evidence verification is the safe read-only path.
- Do not load the sample into a production PostgreSQL database for a demo.
- Fresh extraction cache fingerprints intentionally ignore old cache entries.
  Live backend selection can therefore incur new provider calls after deployment.
- Empty extraction and unknown rules are CHECK, not a promise of eligibility.
- A copied source quote can still be semantically misinterpreted. Always confirm
  the current official notice.
