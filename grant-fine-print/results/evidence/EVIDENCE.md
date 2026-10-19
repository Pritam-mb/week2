# Offline benchmark evidence

This bundle contains **25 notices x 5 constructed profiles = 125 labelled pairs**. The public benchmark is 25 notices x 5 profiles = 125 pairs; synthetic fixtures may be smaller.

## Interpretation and limits

- Labels are single-author judgements under the included rubric; there is no independent inter-annotator agreement estimate.
- These artifacts have seen diagnostic/development reuse. Treat results as a small development benchmark, not an untouched independent holdout or a causal estimate of fine-tuning benefit.
- Pairs share notices and profiles: the effective notice-level sample is 25, not 125 independent observations.
- Verification recomputes canonical metrics with bundled src.eval. Inference is NOT rerun; no training, provider calls, or keys are needed. Recorded latency is historical, not measured by verification.
- Source text is copied only from the public labels CSV (also deduplicated in data/source_text.json). No raw API/contact payloads, logs, environment files, private configuration, or provider/checkpoint metadata are bundled.
- Cost is null: eval_config.json is an intentionally empty, public metric configuration; no provider prices or local config are assumed.
- Confirm in the original notice; this is a screening aid.

## Fresh canonical metrics

| System | Accuracy | Missed eligible grants | Human CHECK | Disqualified -> eligible |
|---|---:|---:|---:|---:|
| code_only | 70/125 | 0/33 | 48/125 | 14/65 |
| fine_tuned | 29/125 | 2/33 | 101/125 | 0/65 |
| prompted | 47/125 | 20/33 | 64/125 | 1/65 |

See eval.json for all metrics and eval_report.html for definitions.

## Three worked examples

Selection is deterministic: sort (opportunity_id, profile_id) lexically, take the first qualifying pair not already used (reuse only if necessary). The restriction miss requires truth NOT_ELIGIBLE and baseline ELIGIBLE. The correct reject also requires an exact whitespace-normalised, source-valid label quote. The final category prefers any fine-tuned label disagreement; only if none exists does it use a CHECK. These are illustrative categories, not a representative random sample. Full rows and public source text are in examples.json.

### baseline_missed_restriction: 356309 / p_university
- Qualifying candidates: 14.
- Label: **NOT_ELIGIBLE**; code_only: **ELIGIBLE**; fine_tuned: **CHECK**.
- Label restriction: fund federally recognized American Indian/Alaska Native (AI/AN) Tribes, tribal colleges or universities, Tribal health programs, or Tribal organizations
- Fine-tuned disqualifier quotes: []
- Fine-tuned CHECK quotes: ["Non-domestic (non-U.S.) Entities (Foreign Institutions) are not eligible to apply", "Non-domestic (non-U.S.) components of U.S. Organizations are not eligible to apply", "Foreign components, as defined in the NIH Grants Policy Statement, are not allowed."]
- Fine-tuned disagreement with label: True.

### fine_tuned_correct_reject: 362480 / p_forprofit
- Qualifying candidates: 5.
- Label: **NOT_ELIGIBLE**; code_only: **NOT_ELIGIBLE**; fine_tuned: **NOT_ELIGIBLE**.
- Label restriction: Only the Lead State Agency (or Agencies) as determined by the Governor of each Highlands State may be the applicant for funding under the Highlands Conservation Act Grant Program.
- Fine-tuned disqualifier quotes: ["Only the Lead State Agency (or Agencies) as determined by the Governor of each Highlands State may be the applicant for funding under the Highlands Conservation Act Grant Program."]
- Fine-tuned CHECK quotes: []
- Fine-tuned disagreement with label: False.

### fine_tuned_failure_or_CHECK: 328026 / p_forprofit
- Qualifying candidates: 96.
- Label: **CHECK**; code_only: **CHECK**; fine_tuned: **ELIGIBLE**.
- Label restriction: (none labelled)
- Fine-tuned disqualifier quotes: []
- Fine-tuned CHECK quotes: []
- Fine-tuned disagreement with label: True.

## Offline rerun

From this bundle's root, using Python 3.10+:

```text
python -m src.evidence_bundle verify --bundle .
```

The verifier uses the standard library, validates hashes and exact pair coverage, and compares freshly recomputed metrics and examples with the stored outputs. Bundled code contains only the evaluator, quote helpers, data models, and this CLI. No installation is needed for verification.

Optional canonical evaluator CLI (requires the project's PyYAML dependency):

```text
python -m src.eval --config eval_config.json --labels data/labels.csv --predictions-dir predictions --out eval.rerun.json --report eval.rerun.html
```

The optional command writes eval.rerun.*; remove those extra files before strict bundle verification. provenance.json records SHA256 and byte size for every payload file, including executable source. The manifest excludes itself (a file cannot contain its own SHA256); these hashes establish internal consistency, not an external authenticity signature.
