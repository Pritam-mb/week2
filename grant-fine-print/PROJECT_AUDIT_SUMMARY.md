# Grant Fine Print — implementation and submission handoff

Updated: 2026-10-19. This is local implementation status, not a claim that remote
services or the Render deployment were revalidated during this work.

## Goal and state

Improve correctness and judge-verifiable evidence within the submission window,
then provide an updated unpublished `DEVTO_SUBMISSION.md`. Original benchmark
predictions remain separate from current-matcher diagnostics.

Implemented:
- Conservative matching for ambiguous alternative lists; whole-phrase organization
  recognition; U.S./non-U.S. exclusion polarity; empty extraction becomes CHECK.
- Explicit escaped CHECK reasons on client cards, with backward-compatible rows.
- Full source/prompt/model/settings cache fingerprints; legacy caches are ignored.
- Strict extraction schema and truncated-output handling: invalid results fail
  visibly rather than masquerading as successful empty extraction.
- Portable, key-free evidence bundle with original predictions, labels/source text,
  profiles, examples, evaluator, and SHA256 manifest.
- Separate offline current-matcher replay from an allowlisted condition snapshot.
- Submission and app evidence page distinguish historical results from replay.

No new fine-tune or remote inference was run. Model-assisted training targets
contain semantic errors; more epochs on them are not a defensible improvement.
Future configuration aligns Qwen3.5 with reasoning-disabled rendering, but this
does not alter the recorded historical checkpoint.

## Earlier measured results (archived; current follow-up below)

25 notices × five constructed profiles; 125 pairs with single-author labels.
The dataset has now seen diagnostic reuse: it is not an untouched holdout.

| System | Eligible wrongly rejected | Disqualified called eligible | CHECK | Correct automatic decisions |
|---|---:|---:|---:|---:|
| Original code-only | 0/33 | 14/65 | 48/125 | 53/77 |
| Original prompted | 20/33 | 1/65 | 64/125 | 30/61 |
| Original fine-tuned | 2/33 | 0/65 | 101/125 | 12/24 |
| Prompted cache + hardened matcher | 2/33 | 0/65 | 108/125 | 14/17 |
| Fine-tuned cache + hardened matcher | 2/33 | 0/65 | 117/125 | 5/8 |

Replay is not new inference, authenticated checkpoint evidence, or a causal
fine-tuning result. Source-substring validity does not establish rule semantics.
That earlier fine-tuned replay's exact labelled-quote agreement was 0/8: there is still substantial
work before automatic decisions should be trusted.

## Files and decisions

- `src/match.py`, `src/models.py`, `src/cards.py`: matcher correctness and review reasons.
- `src/extract.py`: strict output/cache parsing, duplicate-key rejection, full cache identity.
- `src/eval.py`: automatic coverage/accuracy and broader false-eligibility metrics.
- `src/evidence_bundle.py`, `results/evidence/`: immutable original-output evidence.
- `src/matcher_replay.py`, `results/matcher_replay/`: current-code diagnostic, no provider calls.
- `app/templates/evidence.html`: historical-result warning and mixed-cache timing caveats.
- `config.yaml`: Qwen3.5 default matches recorded deployment choice; future training
  renderer disables thinking to match serving. No new checkpoint was created.
- `DEVTO_SUBMISSION.md`, both READMEs, `docs/DEMO_OFFLINE.md`: accurate presentation
  and safe verification instructions instead of overwriting evidence with mock runs.
- New safety, matching, review-reason, bundle, and replay tests plus existing test additions.

An independent code review found two integration gaps: current rows' `check_reasons`
were absent from the bundle allowlist, and duplicate JSON keys bypassed strict cache
validation. Both were fixed and covered with regression tests.

## Actual checks

From `D:\week2\grant-fine-print` (base HEAD `3b0ce1f`, branch `main`, local edits):

- **Tests passed:** `$env:PYTHON_DOTENV_DISABLED = '1'; & "D:\week2\.venv\Scripts\python.exe" -B -m pytest -q -p no:cacheprovider`
  → **378 passed in 32.51s**. No live-model quality claim follows from this.
- **Original bundle passed:** `python -B -S -m src.evidence_bundle verify --bundle results/evidence`.
- **Snapshot replay passed:** `python -B -S -m src.matcher_replay --bundle results/evidence --snapshot results/matcher_replay/conditions_snapshot.json --output <fresh-directory>`;
  exercised in an approved temporary directory and reproduced the reported counts.
- **Diff check passed:** `git diff --check` (Git emits line-ending notices).
- **Build/typecheck/lint:** no separate project commands run; not claimed passed.
- **Remote training, live inference, deployment, customer pilot, second annotator:** not run.

## Before publishing

1. Review `DEVTO_SUBMISSION.md`; it remains `published: false`. If the challenge
   requires an agent-session embed, add the actual share link; no link was invented.
2. Commit/push the intended code and public evidence bundle only when authorized.
   The new GitHub evidence links will not resolve remotely until files are pushed.
3. Deploy and smoke-check the Render app before changing the post's local/not-deployed
   wording. Legacy extraction caches are intentionally cold under the new fingerprint,
   so live screening can trigger new billable calls; plan the subset and spend first.
4. Next substantive model step: independently correct training semantics, preserve
   non-overlapping development/holdout notices, then run paired fresh inference.

No process was started or stopped for a preview. Nothing was committed, pushed,
deployed, or published in this session.

## Follow-up: bounded source semantics and shorter submission

The user asked to proceed with useful narrow improvements rather than more prose.
`src/source_rules.py` was implemented against synthetic cases without benchmark
access. It recognizes complete supported source sentences, not keyword hits, and
can resolve organizational foreign-entity exclusions classified as citizenship.
It treats supported complete applicant alternatives as a union, rejects mismatched
metadata, and leaves components/individual citizenship/qualifiers for review.

Integration audit exposed remaining keyword-only rejection paths: a positive IHE
branch was treated as exclusive, its campus location was applied to a nonprofit,
and a waiver-qualified exclusion could fall back to keywords. Automatic conflicts
now require the bounded source interpreter; fallback keyword conflicts become CHECK.
Existing regression assertions were updated to reflect this intentionally narrower
contract, with new synthetic adversarial tests.

### Current artifacts and observed result

- `results/source_semantics/`: latest replay, with `source_rules.py` in code hashes.
- `reports/proof_pack/PROOF.md`, `examples.json`, `index.html`, `provenance.json`:
  all qualifying catches, a traceable browser preview, and the honest failure.
- `src/proof_pack.py`, `tests/test_proof_pack.py`: validated public-input generator.
- `DEVTO_SUBMISSION.md`: shorter draft led by a real BTOD baseline-miss catch.
- READMEs and evidence-page warning point to the current diagnostic.
- `results/matcher_replay/` remains the earlier archived diagnostic; transient
  follow-up outputs were removed, not substituted for its historical record.

Current fine-tuned-cache replay: **five automatic rejections, all agreeing with author
labels; 120/125 CHECK; no ELIGIBLE predictions; 4/5 exact labelled-sentence agreement**.
Three rejections (359701, 360446, 360541 against p_nonus) correct code-only ELIGIBLE
decisions using relevant verified foreign-organization exclusions. All three are
the same profile and rule family; they do not demonstrate broad generalization.
Prompted-cache replay also has five label-correct rejections and 120 CHECKs; a
contradictory eligibility list in its 358934 source remains an ambiguity. The
source grammar does not semantically adjudicate the full notice.

No fine-tuning or remote inference was run. This is reused development data,
single-author labels, constructed profiles, and unauthenticated legacy model identity.
The fine-tuned catch is a **matcher-enabled use of an existing extraction**, not a
training gain. Low automation remains unsolved.

Correction to the prior draft: 328026 extraction was **not empty**. It extracted
one mixed applicant list and omitted the no-applications status sentence. Its current
CHECK reason is grouping ambiguity, not detected closure. The post and proof pack
now state that accurately.

Next publication step is still authorized commit/push and deployment verification;
none has been done. An actual agent-session URL must be supplied if required.

### Follow-up verification and preview

- Full suite: `$env:PYTHON_DOTENV_DISABLED = '1'; & "D:\week2\.venv\Scripts\python.exe" -B -m pytest -q -p no:cacheprovider`
  → **893 passed in 48.61s** (supersedes the earlier 378-test run).
- Original portable evidence verification passed again.
- Re-generated the proof pack to an approved temporary directory with
  `python -B -S -m src.proof_pack --bundle results/evidence --replay results/source_semantics --output <fresh-directory> --hero-id 360446`:
  5 automatic/120 CHECK, three qualifying catches, all input/code hashes valid.
- `git diff --check` initially found Markdown hard-break trailing spaces in the
  short summary; these were replaced with explicit line breaks and rechecked.
- Static preview started on **http://localhost:8765/**, serving only
  `reports/proof_pack/`, process **20536** at launch. HTTP smoke check returned
  **200**, with offline banner and hero 360446 present. This is not the Flask app
  or remote model inference. Inspect with `Get-Process -Id 20536` if still running.
- No fresh training, remote inference, external user validation, deployment, commit,
  push, or publication occurred. Lint/typecheck/build commands were not run.
