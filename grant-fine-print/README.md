# Grant Fine Print — quote-or-abstain screening

A weekly **one-page fine-print card** for freelance grant writers: it reads the
free-text eligibility rules in Grants.gov opportunities, checks them
against each client's profile, and says which grants to pursue, which to rule
out (with the exact sentence that rules them out), and which need a human read.

[Grants.gov](https://grants.gov) is the evaluated source; an EU adapter is a prototype, not benchmarked coverage. This is a
**screening aid, not legal or grant advice** — every card carries the line
"Confirm in the original notice."

![Grant Fine Print Multi-Client Dashboard](docs/images/dashboard_preview.jpg)

## What it does

Grants.gov's applicant-type facet filters on a code; for opportunities coded
"Others" the code tells you nothing and the real rules live in a free-text
eligibility field. Grant Fine Print reads that text in two stages:

1. **Stage 1 — extract conditions (the model).** Once per opportunity (cached
   by full text, prompt, model/checkpoint, and generation-settings fingerprint), a small model reads the eligibility text and synopsis and
   returns structured conditions, each carrying a **verbatim quote** copied
   from the source (`src/extract.py`).
2. **Stage 2 — match (plain code).** `src/verify.py` drops any condition whose
   quote, after whitespace normalisation, is not a substring of the source
   text. `src/match.py` then compares the verified conditions with a client
   profile: types the code can evaluate (`org_type`, `location`, `size`) are
   decided deterministically; everything else becomes CHECK with source text
   and explicit review reasons. Empty extraction is CHECK, not evidence of eligibility;
   malformed/truncated extraction fails visibly and is not cached as a valid result.

**Quote-or-abstain is enforced in code, not by prompting:** a model-backed NOT ELIGIBLE is
only reachable through a verified, verbatim disqualifying quote
(`src/match.py`); conditions with missing or non-verbatim quotes are dropped
by the verifier and their presence forces CHECK instead of ELIGIBLE. Because
stage 1 runs once per opportunity, model cost does not grow with the number
of clients. A source-valid quote does not guarantee correct rule interpretation.
Human overrides are separately recorded and are not model-generated evidence.

## The Study (Headline Numbers)

Before building the model, we pulled 528 active grant opportunities from Grants.gov
(pull date: **2026-10-17**) to measure the severity of the free-text screening problem:

| Finding | Metric | Count ("k of N") | Why it matters |
|---|---|---|---|
| **(a) "Others"-only opportunities** | Code filter blindness | **180 of 528** (34.1%) | The official filter provides zero signal; writers must manually inspect free text. |
| **(b) Misleading permissive codes** | Hidden hard disqualifiers | **16 of 26** (61.5%) permissive<br>**12 of 15** (80.0%) "Others" | Opportunities coded as open or permissive bury fatal disqualifiers in the text. |
| **(c) Exclusion-language regex hits** | Restriction-language proxy | **221 of 528** (41.9%) | Not 221 confirmed disqualifications; applicability still requires interpretation. |

These figures are computed deterministically in `src/study.py` and stored in
`results/study.json`, with the hand-labelled stratified sample in `data/labels/study_labels.csv`.
The saved sample has 60 rows and seed `20261018`; the reported subgroups are small,
single-author subsets. The catalog is a historical snapshot, not today's live row count.

## Quickstart

```bash
python -m venv .venv
# PowerShell:  .\.venv\Scripts\Activate.ps1
# bash/zsh:    source .venv/bin/activate
pip install -e ".[app,test]"
```

### Environment configuration (`.env`)

The offline sample commands use the deterministic `MockBackend` with **zero
network access and zero keys**. Production prompted/fine-tuned runs require a
real provider and never silently fall back to mock output.

To configure a real model provider or optional contact links:

1. Copy `.env.example` to `.env` (which is `.gitignore`d to prevent leaking secrets):
   ```bash
   # Linux / macOS:
   cp .env.example .env

   # Windows (PowerShell):
   Copy-Item .env.example .env
   ```
2. Set the variables in `.env`:
   - `GFP_PROVIDER_BASE_URL`: Tinker OpenAI-compatible endpoint.
   - `TINKER_API_KEY`: Tinker API key sent as a `Bearer` token (`GFP_API_KEY` remains a legacy alias).
   - `GFP_BASE_MODEL`: Tinker base model ID.
   - `GFP_FINE_TUNED_MODEL`: Tinker sampler checkpoint path after training.
   - `DATABASE_URL`: Tiger Data PostgreSQL connection string.
   - `GFP_STORAGE=postgres`: Use Tiger Data after initializing/importing the schema.
   - `SERPAPI_KEY`: Optional key for missing official-link discovery only.
   - `GFP_SUPPORT_EMAIL`: (Optional) Product support email displayed in the web app header/footer.
   - `GFP_SUPPORT_PHONE`: (Optional) Product support phone displayed in the web app header/footer.

> **Note:** Product contact links are for Grant Fine Print only — agency contacts
> from Grants.gov are never republished on client cards.

### Core commands

| Command | What it does / writes |
|---|---|
| `python -m src.pull --mock` | Offline pull from `data/samples/mock_opportunities.json` (no network). Writes cached raw JSON to `data/raw/` plus `data/raw/manifest.json`. Use `python -m src.pull` for a live Grants.gov pull (polite rate limits, retries, text-hash deduplication). |
| `python -m src.study` | Computes headline study numbers: (a) "Others"-only count, (c) keyword-filter count, and the stratified sample sheet (b). Writes `results/study.json` and `data/samples/study_sample.csv`. |
| `python -m src.pipeline` | Runs the three systems (`code_only`, `prompted`, `fine_tuned`) across profiles x opportunities: extract → verify → match. Writes JSONL predictions to `results/predictions/` with `.meta.json` sidecars, and renders printable cards to `results/cards/*.html`. |
| `python -m src.eval` | Scores prediction files against labels. Writes `results/eval.json` and an HTML report. Use the evidence verifier for strict duplicate and exact-coverage checks. |
| `python -B -S -m src.evidence_bundle verify --bundle results/evidence` | Verifies the portable original-run bundle and recomputes scores without provider calls, keys, or site packages. |
| `python -B -S -m src.matcher_replay --bundle results/evidence --snapshot results/source_semantics/conditions_snapshot.json --output results/matcher_replay_check` | Replays current bounded rules from public cached-condition snapshots to a fresh folder; diagnostic only, no new inference. |
| `python -m app.main` (or `flask --app app.main run`) | Launches the web app: manage client profiles, refresh Grants.gov data, run screenings, search/sort cards, and record human corrections. |

Useful command options:
- `python -m src.pipeline --systems prompted --corrections`: Applies stored human corrections (`data/corrections/corrections.json`) and renders updated cards.
- `python -m src.pipeline --ids-file data/samples/test_sample.csv`: Restricts execution to specific opportunity IDs.
- `python -m pytest`: Runs the test suite (including the provider, storage, and discovery boundary tests).
- `python -m src.storage init` / `python -m src.storage import-cache`: Initialize and import the Tiger Data store.
- `python -m src.train prepare` / `python -m src.train train`: Prepare reviewed extraction data and train a real Tinker LoRA checkpoint. See [`docs/PRODUCTION_SETUP.md`](docs/PRODUCTION_SETUP.md).
- `gfp <command>`: Console dispatcher installed with the package (`gfp pull`, `gfp study`, `gfp eval`).

## The Web App

The Flask application (`app/main.py`) provides an interactive interface for freelance grant writers:

- **Dashboard (`/`)**: Displays client profiles, cache status (pull date, opportunity count), and model backend status (with an alert if falling back to `MockBackend`).
- **Profile Management (`/profiles/new`)**: Create client profiles with organization type, US state, US-based status, size band, and focus keywords.
- **Grants.gov Sync (`/refresh`)**: Trigger a live polite pull or load the offline mock dataset with one click.
- **Run Screening (`/run`)**: Run the Stage 1 + Stage 2 pipeline across selected or all profiles.
- **Interactive Card Panel (`/card/<profile_id>`)**:
  - Filter opportunities by search keywords or verdict (`LIKELY ELIGIBLE`, `NOT ELIGIBLE`, `CHECK`).
  - Sort by closing date or award ceiling.
  - View verified verbatim disqualifier quotes and source excerpts.
  - Print clean, single-page client cards with provenance (pull date and backend used).
  - Record human corrections inline ("this is wrong").
- **Human Corrections (`/correct`)**: Store human-in-the-loop overrides in `data/corrections/corrections.json` to correct edge cases over time.
- **Health Probe (`/healthz`)**: Operational health check endpoint for monitoring and cloud deployment.

## Using a real model (stage 1)

The deterministic **MockBackend** is only for the explicit offline demo. To
point stage 1 at a real model:

- Set environment variables `GFP_PROVIDER_BASE_URL` (the Tinker OpenAI-compatible
  base URL; the code calls `{base}/v1/chat/completions`, or
  `{base}/chat/completions` when the URL already ends in `/v1`) and
  `TINKER_API_KEY` (sent as a Bearer token). See `.env.example`.
- Or set the same knobs in `config.yaml` under `extract:`:
  `provider_base_url`, `base_model` (the prompted baseline model, default
   `Qwen/Qwen3.5-4B`), `fine_tuned_model` (must be set before a
  `fine_tuned` run will work), and `provider` (informational label:
  `tinker | openai-compatible | mock`).

If the provider, key, or fine-tuned checkpoint is missing, a production model
run stops with a configuration error. This prevents a real evaluation from
being silently replaced with mock output. Choose the mock backend explicitly
for offline plumbing tests. A `fine_tuned` run requires
`extract.fine_tuned_model` to be set.

## Evaluation & Results — original saved run

Evaluation follows strict principles:
- **Frozen Labels**: Test labels are committed and tagged before model runs (`data/labels/test_labels.csv` for the live test set, `data/labels/test_labels.mock.csv` for offline tests, labelled under `data/labels/rubric.md`).
- **Primary Trade-off**: Missed-grant rate (must be as close to zero as possible) vs. human-read share (the fraction of opportunities left for manual reading).
- **Quote Validity**: Evaluated before code enforcement to measure raw model hallucinations. The verifier drops non-verbatim quotes, safely turning potential false NOT ELIGIBLEs into CHECK.
- **Quote Correctness**: Reported separately from source validity. A quote can occur in the notice without being the right sentence for the labelled disqualification.
- **Publishing Negative Results**: All systems are evaluated on the exact same 125 opportunity-profile pairs (5 constructed profiles x 25 unique opportunities). The effective notice-level sample is 25; the pair count tests profile matching as well as extraction.

| System | Missed-Grant Rate (Primary) | Human-Read Share (CHECK) | Quote Validity | Quote Correctness |
|---|---|---|---|---|
| **`code_only`** (Baseline) | **0 of 33** (0.0%) | **48 of 125** (38.4%) | N/A (code-only) | 0 of 33 (0.0%) |
| **`prompted`** (Base Model) | 20 of 33 (60.6%) | 64 of 125 (51.2%) | **94 of 95** (98.9%) | 13 of 54 (24.1%) |
| **`fine_tuned`** (Tinker) | **2 of 33 (6.1%)** | 101 of 125 (80.8%) | **18 of 18** (100.0%) | 5 of 18 (27.8%) |

On this saved run, `code_only` achieved the lowest missed-grant rate (0.0%), but called 14 of 65 disqualified pairs likely eligible. Outputs recorded as fine-tuned had 2 of 33 missed eligible grants versus 20 of 33 for prompted, with **18/18 source-valid proposed disqualifier quotes**. This is not an isolated causal estimate of training benefit: downstream matcher behavior and historical cache provenance also matter. The original fine-tuned system routed 101 of 125 pairs to CHECK.

These are **historical outputs**, not scores for the hardened matcher. None of the
33 eligible pairs was correctly called eligible by the original fine-tuned system:
31 were CHECK and two were rejected. Only 12 of its 24 automatic decisions were
correct. Source validity is not semantic correctness or a safety guarantee.

### Current bounded source-rule diagnostic (no new inference or training)

`src/source_rules.py` interprets a closed grammar of complete quoted restrictions.
It distinguishes foreign organizations from foreign components and citizenship,
and handles fully supported applicant alternatives as a union. Unsupported keyword
conflicts cannot automatically reject an applicant: one permitted category is not
proof that other routes are excluded. Empty extractions still require review.

| Legacy cached input + current matcher | Missed eligible | Disqualified → eligible | CHECK | Correct automatic decisions |
|---|---:|---:|---:|---:|
| Prompted | 0/33 | 0/65 | 120/125 | 5/5 |
| Fine-tuned | 0/33 | 0/65 | 120/125 | 5/5 |

The five fine-tuned-cache rejections include **three genuine code-only misses**:
359701, 360446, and 360541 against the constructed UK nonprofit `p_nonus`.
All three use the same organizational-geography rule family. Original fine-tuned
output was CHECK; the same cached quotes now support rejection via the matcher.
This is not a model-training gain. Only **5/125 decisions are automatic**, all
rejections; no eligible pair is automatically cleared. Five label agreements do
not establish generalized precision. The prompted stream's full-source ambiguity
remains a limitation; source-substring checks do not adjudicate the whole notice.

Hardening increases abstention; it does not establish improved useful automation.
Labels have seen diagnostic reuse and are single-author. Legacy cache identities
cannot authenticate the model/checkpoint. New caches use a full fingerprint and
never silently reuse legacy entries; **deploying this change will make old caches
cold**, so a live run may incur fresh provider calls. A new fine-tune was not run:
semantic errors in training targets need correction before more optimization.

- [`results/evidence/EVIDENCE.md`](results/evidence/EVIDENCE.md): portable original
  predictions, source text, profiles, examples, evaluator, SHA256 provenance.
- [`results/source_semantics/REPLAY.md`](results/source_semantics/REPLAY.md): current
  post-hoc replay, condition snapshot, verdict changes, and reproduction.
- [`reports/proof_pack/PROOF.md`](reports/proof_pack/PROOF.md): all three catches,
  actual quotes/profile facts, and the corrected account of the notice-of-intent failure.
- [`reports/proof_pack/index.html`](reports/proof_pack/index.html): self-contained
  offline browser comparison, not a live inference demo.
- `results/matcher_replay/`: archived earlier hardening diagnostic, not current output.
- `results/eval_report.html` / `results/eval.json`: original-run reporting.
- [`DEVTO_SUBMISSION.md`](DEVTO_SUBMISSION.md): updated, unpublished submission draft.

The bundle verifier recomputes metrics, not inference. Test-source IDs and source
hashes do not overlap the 100 training examples, but a fresh independent holdout
and second-annotator check are still needed. New local changes are not deployed.

## Project layout

```
grant-fine-print/
  config.yaml            all knobs: API, cache, models, code mappings, thresholds
  render.yaml            Render Blueprint (web service + manual refresh)
  .env.example           provider & app env vars (copy to .env; never commit secrets)
  pyproject.toml         package dependencies, scripts, and pytest configuration
  src/
    pull.py              fetch + cache + dedupe opportunities (--mock for offline)
    study.py             headline numbers (a), (c) + sample sheet for (b)
    extract.py           stage 1: prompted / fine-tuned / mock backends, cached
    verify.py            quote verification (verbatim-substring check)
    match.py             stage 2: deterministic profile matching
    source_rules.py      bounded whole-quote interpretation; no keyword-only rejection
    baseline.py          code-only baseline (applicant-type codes, no model)
    pipeline.py          end-to-end glue: extract → verify → match → cards
    cards.py             printable one-page HTML card per profile with provenance
    eval.py              PRD 8.5 metrics + HTML report with inline charts
    corrections.py       per-(profile, opportunity) human overrides
    cli.py               `gfp` dispatcher
    adapters/            multi-source ingestion contracts (BaseSourceAdapter, GrantsGovAdapter)
    config.py, io_utils.py, models.py
  app/
    main.py              Flask application & route handlers
    templates/           Jinja2 templates (dashboard, cards, new profile, run summary, errors)
    static/              app.css, favicon.svg
  data/
    raw/                 cached API JSON: <id>__<hash-prefix>.json + manifest.json
    mock_raw/            committed offline sample JSONs + manifest
    samples/             offline mock opportunities + study sample sheets
    labels/              test_labels.csv (frozen), test_labels.mock.csv, study_labels.csv, rubric.md
    profiles/            client profiles (constructed, disclosed)
    corrections/         human-applied overrides (corrections.json)
    extract_cache/       source/prompt/backend fingerprint cache plus historical entries
  results/
    study.json           headline study findings
    eval.json            comprehensive evaluation metrics & confusion matrices
    eval_report.html     self-contained visual evaluation report
    predictions/         <system>.jsonl + <system>.meta.json
    cards/               one printable HTML card per profile
  tests/                 pytest suite (matcher, extraction safety, review reasons, evidence replay)
  docs/
    DEMO_OFFLINE.md      operator guide for zero-network execution
```

## Data handling rules

- Raw API JSON is cached in `data/raw/` as `<id>__<12-hex-text-hash>.json`
  with a manifest (`data/raw/manifest.json`) recording the **pull date**,
  totals, new/changed/duplicate counts. Live pulls never re-fetch an
  opportunity whose text hash is unchanged.
- Stage-1 extractions are cached by full source/prompt/backend identity fingerprint
  (`data/extract_cache/extract-sha256-v2/`). Changing the model, checkpoint, prompt,
  or generation settings misses the old cache. Legacy entries are not reused.
- Do **not** republish agency contact details: the cards render agency name,
  close date, award range and the Grants.gov link only — never contact
  emails or phone numbers, even though the pull may cache them.
- Cite [Grants.gov](https://grants.gov) as the authoritative source and check
  its terms of use before redistributing opportunity text; results state the
  pull date because opportunities and amendments change afterwards.

## Deployment on Render

A production-ready [render.yaml](file:///d:/week2/grant-fine-print/render.yaml) Blueprint is included:

- **Web Service**: Runs with Gunicorn: `gunicorn "app.main:create_app()" --bind 0.0.0.0:$PORT`.
- **Secrets**: Add `GFP_PROVIDER_BASE_URL` and `GFP_API_KEY` in the Render dashboard.
- **Refresh Flow**: The web interface provides an in-app "Refresh Grants.gov" button, eliminating the need for a separate cron container writing across ephemeral container disks on the free tier.

## Honest limits

- Ingestion supports US Federal Grants (Grants.gov) and a prototype European Union Grants (EU Funding & Tenders Portal) adapter via `BaseSourceAdapter`, with a pre-registered contract for Canada Grants. The benchmark covers Grants.gov only.
- The client profiles in the test set are constructed (disclosed as such).
- Small test set: results come with counts, not tight percentages.
- Training labels are model-assisted; test labels are hand-made.
- This is a screening aid, not legal or grant advice. Always confirm in the
  original notice.
- Opportunities and amendments change after the pull date.
- Offline runs use MockBackend only when explicitly requested: a pipeline smoke
  test, **not** real model results (see `docs/DEMO_OFFLINE.md`).

## Product boundaries

The app deliberately does not use general web search as eligibility evidence.
Grants.gov is the source of truth, and only a verified verbatim quote from the
cached notice can produce **NOT ELIGIBLE**. SerpApi could be added later as an
auxiliary finder for a missing official link, but search snippets must never
change a verdict. Mastra is also intentionally deferred: this Python pipeline
already has the useful staged workflow (extract, verify, match, human
correction), and adding a second runtime would not improve its trust boundary.
