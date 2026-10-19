# Offline public proof pack

Offline development evidence preview—not live inference

FINAL fine-tuned replay: 5/125 automatic, 120 CHECK, 5/5 automatic label agreement.

The code-only baseline has greater automatic coverage: 77/125 automatic, 48 CHECK; 53/77 automatic label agreement. Agreement on a small automatic subset must be read alongside abstention.

FINAL input: `results/source_semantics`.

## All qualifying catches

ALL original code_only ELIGIBLE -> CURRENT FINAL replay_fine_tuned NOT_ELIGIBLE pairs labelled NOT_ELIGIBLE; lexical pair order. Every candidate must have a verified actual disqualifier interpreted as conflict.

All 3 catches share profile p_nonus and rule family organizational geography / excluded. They do not demonstrate broad rule coverage.

| Notice | Profile | Label | Code-only | FINAL fine-tuned | Interpreter |
|---|---|---|---|---|---|
| 359701 | p_nonus | NOT_ELIGIBLE | ELIGIBLE | NOT_ELIGIBLE | conflict |
| 360446 | p_nonus | NOT_ELIGIBLE | ELIGIBLE | NOT_ELIGIBLE | conflict |
| 360541 | p_nonus | NOT_ELIGIBLE | ELIGIBLE | NOT_ELIGIBLE | conflict |

## Three illustrative comparisons

Hero selected by --hero-id with p_nonus; second selected by --second-id or first other lexical candidate; honest CHECK fixed at 328026/p_forprofit. Illustrative, not a random sample.

### hero: 360446 / p_nonus
Label **NOT_ELIGIBLE**; code-only **ELIGIBLE**; original fine-tuned **CHECK**; FINAL fine-tuned **NOT_ELIGIBLE**.

> Non-domestic (non-U.S.) Entities (Foreign Organizations) are not eligible to apply.

Actual FINAL disqualifier re-verified against full source; interpreter returns **conflict**. Membership in the quoted group: **True**, derived via the interpreter.

Full source SHA256: `5e960b317bc0403943e405668cf00b9d285a278960dc1c9819e6a80c62a25efb`; pointer `results/evidence/data/source_text.json` key `360446`.

### another_catch: 359701 / p_nonus
Label **NOT_ELIGIBLE**; code-only **ELIGIBLE**; original fine-tuned **CHECK**; FINAL fine-tuned **NOT_ELIGIBLE**.

> Non-domestic (non-U.S.) Entities (Foreign Organizations) are not eligible to apply.

Actual FINAL disqualifier re-verified against full source; interpreter returns **conflict**. Membership in the quoted group: **True**, derived via the interpreter.

Full source SHA256: `101b33228d33ee01e9ccd9f446e50e91c5b34036c25b316d10f104e51d4e9dfd`; pointer `results/evidence/data/source_text.json` key `359701`.

### honest_CHECK: 328026 / p_forprofit
Label **CHECK**; code-only **CHECK**; original fine-tuned **ELIGIBLE**; FINAL fine-tuned **CHECK**.

**Why CHECK (actual prediction reason):** The source quote lists multiple organization types; review how the listed applicants are grouped.

One nonempty mixed applicant-list condition was extracted. The actual CHECK reason concerns applicant grouping. The separate not-accepting-applications text is present in full source but omitted from extraction; it is context, not the recorded CHECK reason.

> This is a notice of intent and no applications are being accepted at this time.
> We are not accepting applications at this time.

Full source SHA256: `8661b622460b6e840c179b2097486f358463737b8e85d162a815a2be21afbcb4`; pointer `results/evidence/data/source_text.json` key `328026`.

## Scope and reproduction

Reused development set; single-author labels; constructed profiles. Pairs share notices and profiles and are not independent observations. No generalization claim or causal fine-tuning improvement estimate is supported. Cached backend names do not authenticate model/checkpoint identity. No inference was rerun. Software re-checks quote presence against the full bundled source and interprets only the chosen restriction; the full source is NOT semantically adjudicated by software. Hashes establish consistency, not external authenticity.

Both input manifests' entire payload inventories and hashes, exact pair coverage for every prediction system, snapshot/source hashes, original copies and FINAL metrics were checked. Inputs are read only. Existing output directories are refused.

From the project root (use a fresh output directory to repeat):

```text
python -B -m src.proof_pack --bundle results/evidence --replay results/source_semantics --output reports/proof_pack --hero-id 360446
```

`examples.json` contains all candidates, the three examples, conditions, actual review reasons, label/profile/prediction pointers and full-source hashes; it omits full raw source/contact payloads. `provenance.json` records input manifest hashes, current code/test hashes, original replay code hashes and output payload hashes. Open `index.html` directly for the self-contained comparison preview.
