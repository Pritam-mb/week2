---
title: "The applicant code said yes. The grant's fine print said no."
published: false
tags: devchallenge, hf26challenge, opensource, ai
cover_image: https://raw.githubusercontent.com/Pritam-mb/week2/main/grant-fine-print/docs/images/btod-hero.png
---

*This is a submission for the [Hacktoberfest Open-Source AI Challenge Week 2: Side Hustle](https://dev.to/challenges/hacktoberfest-week2-2026-10-12).*

**Grant Fine Print turns grant eligibility text into evidence-backed client screening cards.** It is built for freelance grant writers and small consultancies checking opportunities for several clients—not for replacing their judgment.

[Open the app](https://grant-fine-print.onrender.com/) · [Browse the source](https://github.com/Pritam-mb/week2/tree/main/grant-fine-print) · [Open the worked-example demo](https://grant-fine-print.onrender.com/proof/) · [Inspect the evidence](https://grant-fine-print.onrender.com/evidence)

The short version:

- **The problem:** applicant-type codes cannot express every restriction buried in a notice.
- **The product:** client profiles, source refresh, structured extraction, quote checks, deterministic matching, printable cards, explicit review reasons, and human corrections.
- **The demonstrated catch:** three code-only mistakes corrected using verified foreign-organization restrictions, all involving one constructed UK profile and one rule family.
- **The honest boundary:** the current development replay leaves **120 of 125 pairs for human review**. It is not a fresh inference run, an untouched holdout, or proof that fine-tuning outperforms prompting.

## What I Built

### The fine print that changes the verdict

Consider **BTOD Centers, opportunity 360446 / PAR-27-024**, screened for **Meridian Health Trust**, a constructed UK nonprofit profile.

The applicant-code baseline says **ELIGIBLE**. The notice says:

> Non-domestic (non-U.S.) Entities (Foreign Organizations) are not eligible to apply.

The same notice separately allows **foreign components**. These are not interchangeable: a foreign organization applying is different from a domestic organization including a foreign component.

The historical extraction copied the relevant sentence but classified it as `citizenship_or_residency`. The old matcher returned CHECK. The current bounded sentence interpreter recognizes the explicit **organizational** exclusion, compares it with `us_based: false`, and returns NOT_ELIGIBLE with the verified sentence.

| Same notice, same constructed client | Result |
|---|---|
| Applicant-code baseline | ELIGIBLE |
| Original fine-tuned-labelled output | CHECK |
| Historical cached conditions + current matcher | NOT_ELIGIBLE |
| Author's reference label | NOT_ELIGIBLE |

![Generated BTOD proof card comparing the code-only result with the source-rule replay and displaying the exact foreign-organization exclusion](https://raw.githubusercontent.com/Pritam-mb/week2/main/grant-fine-print/docs/images/btod-hero.png)

*Screenshot 01 — Generated proof card, not a live application screenshot. It is built from the saved profile, predictions, and source-checked quote. Its footer states the development-replay scope and 120/125 CHECK count.*

**This improvement is in rule interpretation, not model weights.** The prompted-cache stream supports the same catch. Historical backend labels do not authenticate the producing model or checkpoint.

Two more pairs—**359701 / C06 research facilities** and **360541 / SPOREs**, both with the same UK profile—show the same baseline correction. They are three illustrative pairs, not three independent capabilities. The [proof notes](https://github.com/Pritam-mb/week2/blob/main/grant-fine-print/reports/proof_pack/PROOF.md) list every qualifying catch rather than selecting only a flattering example.

## Demo: The Complete Feature Walkthrough

### 1. Multi-client dashboard and profile directory

The dashboard shows available client profiles, the opportunity count, source-cache information, and backend selection. A writer can move between clients instead of rebuilding the same shortlist from scratch. The separate `/profiles` page lists the client roster.

![Grant Fine Print dashboard and multi-client screening interface](https://raw.githubusercontent.com/Pritam-mb/week2/main/grant-fine-print/docs/images/dashboard_preview.jpg)

*Screenshot 02 — Existing dashboard screenshot. Counts, verdicts, and pull dates belong to the captured run; they are not the current benchmark or a promise of today's catalog size.*

### 2. Custom client onboarding

At `/profiles/new`, a writer creates a profile containing:

- Organization name and type: nonprofit, for-profit, small business, university, tribal, government, individual, or other.
- U.S.-based status and state.
- Size band, focus keywords, and notes.

The form validates required fields and handles duplicate-name slugs. The saved facts drive matching; focus keywords help order relevant opportunities, not prove eligibility.

<!-- SS03: Replace the following capture note with an uploaded, redacted screenshot. No image is available in the repository yet. -->
> **Screenshot 03 placement — Client profile form:** capture `/profiles/new` with a clearly fictional client, organization type, U.S.-based checkbox, state, size, and focus keywords visible. Caption: “Create a reusable client profile before screening.”

### 3. Source refresh, explicit offline mode, and screening runs

The refresh flow offers a **live Grants.gov pull** or an explicitly labelled **offline sample**. The live pull caches official notice text and tracks source revisions through text hashes. The sample is for exercising product plumbing, not demonstrating model accuracy.

From the screening controls, a writer can run a selected profile or all profiles with the chosen backend. The run summary reports the backend actually used, opportunity/profile counts, verdict totals, and links to generated cards.

Production prompted/fine-tuned runs require their provider configuration; they do not silently fall back to mock output. The offline sample deliberately uses the deterministic mock backend.

<!-- SS04: Capture only in an isolated demo environment; do not refresh production or spend provider credits just to take a screenshot. -->
> **Screenshot 04 placement — Screening controls and run summary:** show the selected profile, backend, counts, and generated card links. If using the sample, keep the offline/mock label visible. Caption: “A run identifies its backend instead of disguising sample output as live inference.”

### 4. Searchable, filterable, printable client cards

At `/card/<profile_id>`, the writer can:

- Search within screening results and filter by **LIKELY ELIGIBLE**, **NOT ELIGIBLE**, or **CHECK**.
- Sort by relevance, closing date, or award ceiling.
- See agency, deadline, award information where available, and the official notice link.
- Inspect source excerpts and highlighted disqualifying quotes.
- Print the screening sheet, including provenance such as backend and pull date.

![Earlier client card showing a highlighted eligibility restriction and verdict stamp](https://dev-to-uploads.s3.us-east-2.amazonaws.com/uploads/articles/ollpzirjpdbxlp7qp73i.png)

*Screenshot 05 — Earlier application capture illustrating the highlighted-quote card design. This is not the current BTOD replay or evidence that all historical card decisions remain valid under the hardened matcher. The source-linked BTOD proof pack above is the current worked example.*

### 5. CHECK with a reason, not just an uncertain badge

CHECK means the writer still needs to read. Cards can explain why: an empty extraction, unsupported condition, uncertain applicant grouping, missing profile facts, or an unverified quote.

The intended benefit is a review starting point: the relevant extracted clause where available, the reason the code could not decide, and the original notice. **Whether this saves net review time has not yet been measured.**

<!-- SS06: Use a current card generated with controlled data. Do not invent a quote when extraction is empty. -->
> **Screenshot 06 placement — “Why CHECK” explanation:** show an unresolved condition, its actual review reason, and the official source link. Caption: “Unsupported or ambiguous rules stay with the human reviewer.”

### 6. Human corrections and recorded overrides

The card's correction form lets a writer select an opportunity, change its verdict, and add a note. The application validates the profile, opportunity, and verdict before saving. Subsequent UI screening runs apply recorded corrections.

An override is a **human decision recorded separately**, not a model-generated quote or automatically verified training label. The current form handler saves through the filesystem correction path; the PostgreSQL integration also provides correction persistence methods.

<!-- SS07: Use fictional client details and a non-sensitive note; do not submit demonstration corrections to production. -->
> **Screenshot 07 placement — Correction form and saved entry:** capture “This is wrong,” the revised verdict, a short review note, and the correction list. Caption: “A grant specialist can challenge a result and leave a review trail.”

### 7. Evidence, downloadable charts, and a key-free proof demo

The `/evidence` page presents the saved catalog study and historical three-system benchmark, with warnings distinguishing those outputs from current code. Charts can be exported as PNGs.

The separate [read-only `/proof/` demo](https://grant-fine-print.onrender.com/proof/) serves a self-contained comparison of the actual saved predictions, profile facts, verified quotes, and an honest failure case. It does not call a model. Allowlisted proof notes, JSON, provenance, and hero assets are available without exposing arbitrary repository files.

The study and benchmark screenshots appear in the evidence section below; they are historical reporting, not a substitute for the replay table.

### 8. Stack diagnostics and operational health

At `/stack`, the application shows configured storage, source/cache information, profile and correction counts, model/checkpoint configuration, and whether optional provider keys are present. PostgreSQL connection/table counts are shown when available. `/healthz` is a lightweight application health response.

Configured keys are **not** proof that a provider call succeeded; a healthy Flask route is **not** a full database/model readiness check.

<!-- SS08: Redact database host/account identifiers, credentials, and any personal details before uploading. -->
> **Screenshot 08 placement — Stack diagnostics:** capture storage status, available counts, source pull date, and model/provider configuration. Caption: “Visible configuration and connection status, without exposing secrets.”

### 9. Source adapters and command-line tools

The ingestion boundary uses `BaseSourceAdapter` and normalized opportunity objects so downstream extraction and matching are not tied to one portal's payload shape.

| Source | Current scope |
|---|---|
| Grants.gov | Implemented source used for the catalog study and saved evaluation. |
| EU Funding & Tenders Portal | Prototype adapter with tests; not part of the reported benchmark. |
| Canada grants | Registered placeholder, not a working evaluated source. |

The repository also exposes CLI flows for pulling notices, screening, generating cards, evaluating saved predictions, initializing/importing the PostgreSQL store, optional official-link discovery, and preparing/training Tinker extraction models. These are developer tools, not a claim of a production scheduler or fully automated weekly delivery.

### 10. A proof-sheet interface rather than a chatbot

The visual language is cream paper, ink typography, offset shadows, rubber-stamp verdicts, and marker-yellow quotes. Light/dark themes, responsive navigation, print styling, and reduced-motion handling support the review workflow. Evidence charts use patterns as well as color.

The goal is for a writer to compare a client fact with a source sentence—not accept an unexplained confidence score.

## How I Built It

```text
Official Grants.gov notice
        |
        v
Saved source snapshot + text hash
        |
        v
Model extraction: structured conditions + source quotes
        |
        v
Python quote verifier: whitespace-normalized substring check
        |
        v
Bounded sentence interpretation + deterministic profile matching
        |
        +--> LIKELY ELIGIBLE: no supported disqualifier found; not a guarantee
        +--> NOT ELIGIBLE: model-backed rejection needs a verified source quote
        +--> CHECK: unresolved evidence or rules require human review
        |
        v
Client card + source link + review reasons + separate human overrides
```

The model proposes conditions; it does not directly issue the final screening verdict. Quote presence is checked in Python, and supported conditions are compared with the profile in code. The bounded source grammar distinguishes foreign organizations from components, individual citizenship, and project location. It handles supported complete applicant alternatives as a union instead of treating every item as a separate mandatory requirement.

Keyword matches alone cannot justify a model-backed rejection. A copied quote can still be misunderstood, and an extraction can omit an important condition, so quote verification is a necessary boundary—not a complete semantic guarantee.

### Reliability and reproducibility work

- **Strict extraction parsing:** malformed JSON, duplicate keys, unexpected schema, and truncated responses fail visibly rather than being cached as successful empty extraction.
- **Empty extraction abstains:** no extracted conditions does not mean the applicant is eligible.
- **Full cache identity:** source, prompt, model/checkpoint, and generation settings contribute to the extraction fingerprint. Legacy entries are not silently reused under the new identity.
- **Reuse across clients:** a matching extraction can be reused for several client profiles. New notices, amended text, or changed extraction settings can require new provider work.
- **Escaped review text:** CHECK explanations and source-derived content are rendered with HTML escaping.
- **Separate evidence streams:** original predictions remain separate from current-code replay; hashes and pair-coverage checks make the saved comparison inspectable.

The implementation uses **Python, Flask/Jinja, Gunicorn, PostgreSQL/psycopg, the Tinker SDK, an OpenAI-compatible inference boundary, SerpApi, and pytest**. Filesystem storage remains available for local/offline use.

## Sponsor Integrations: What Each One Does and Where the Evidence Is

### Tiger Data — versioned official snapshots and PostgreSQL retrieval

Tiger Data's PostgreSQL service on Timescale Cloud supplies the database integration. The current store defines these tables:

| Table | Role |
|---|---|
| `opportunity_snapshots` | Source text, notice metadata, source hashes, capture timestamps, and current/historical revisions. |
| `official_link_candidates` | Discovery metadata for official-link candidates, separate from eligibility evidence. |
| `client_profiles` | Persistence support for reusable client facts. |
| `human_corrections` | Persistence support for human decisions and notes. |
| `rendered_cards` | Persistence support for card HTML and provenance. |

A GIN index supports **PostgreSQL keyword full-text retrieval** over title, agency, synopsis, and eligibility text. This is lexical search, not embeddings or pgvector. Retrieved snippets do not replace the full official snapshot used by the quote verifier.

The distinction between storage support and UI wiring matters: the current profile-creation and correction handlers write local files; not every user interaction is automatically mirrored into PostgreSQL. The card page's displayed database-query timing is not an end-to-end application latency benchmark, so I am not claiming a universal “12 ms screening” result.

**Implementation evidence:** [database schema and store](https://github.com/Pritam-mb/week2/blob/main/grant-fine-print/src/storage.py), [application integration](https://github.com/Pritam-mb/week2/blob/main/grant-fine-print/app/main.py), and [integration-boundary tests](https://github.com/Pritam-mb/week2/blob/main/grant-fine-print/tests/test_integrations.py).

![Previously captured Tiger Data service console](https://dev-to-uploads.s3.us-east-2.amazonaws.com/uploads/articles/4kf82j2b6cv6e0lqgkt0.png)

![Previously captured Tiger Data SQL Explorer](https://dev-to-uploads.s3.us-east-2.amazonaws.com/uploads/articles/7kkin1agsl15nstr3jk0.png)

![Previously captured Tiger Data database tables](https://dev-to-uploads.s3.us-east-2.amazonaws.com/uploads/articles/6jil7mws1c3anr77z9ri.png)

*Screenshots 09–11 — Existing Tiger Data console captures. They document the integration's development history; the linked schema is the reference for current table names. Account/connection details should be redacted before publication.*

### Tinker — the open-weight extraction and fine-tuning experiment

The recorded experiment used **Qwen/Qwen3.5-4B**, a rank-16 LoRA, **100 model-assisted training examples**, three epochs, and a learning rate of **0.0002**. The repository includes preparation and training code using Tinker's SDK, plus the inference backend used for structured extraction.

[Recorded Tinker training session](https://tinker.thinkingmachines.ai/sessions/146167b6-6a85-54ec-bc00-f0489e3f207d) · [Training implementation](https://github.com/Pritam-mb/week2/blob/main/grant-fine-print/src/train.py) · [Extraction backend](https://github.com/Pritam-mb/week2/blob/main/grant-fine-print/src/extract.py)

![Previously captured Tinker training-session overview](https://dev-to-uploads.s3.us-east-2.amazonaws.com/uploads/articles/m0yw6svnle6tb7l9j855.png)

![Previously captured Tinker completed-run view](https://dev-to-uploads.s3.us-east-2.amazonaws.com/uploads/articles/p7tfenhhniy49rkrraep.png)

*Screenshots 12–13 — Existing training-session captures. A training run is not, by itself, proof that a particular legacy prediction came from that checkpoint or that training improved generalization. The session may require its owner's account; public saved evidence is linked below.*

The lesson was not “more training solves it.” A later audit found semantic errors in the training targets. Test-source IDs and hashes do not overlap the training examples, but the evaluation set has since been reused for diagnosis. Correcting target semantics and testing fresh notices are more important next steps than another epoch.

**No new training or remote inference was run for the current matcher replay.** The prompted and fine-tuned-labelled cache streams each produce five automatic rejections under the current code. I am documenting Tinker usage and lessons learned, not claiming a demonstrated fine-tuning advantage.

### SerpApi — official-link recovery, not eligibility evidence

If a notice is missing an official link, the discovery helper searches using the opportunity number or title with `site:grants.gov`. It selects only HTTPS URLs on `grants.gov` or its subdomains. Existing valid official links skip the search; a missing optional key does not fabricate a result.

Discovery is available through the CLI and `POST /discover/<opportunity_id>`. Search titles and snippets are discovery metadata only: they do not become source text, extracted restrictions, or grounds for a verdict.

**Implementation evidence:** [link discovery and URL validation](https://github.com/Pritam-mb/week2/blob/main/grant-fine-print/src/discovery.py) and [boundary tests](https://github.com/Pritam-mb/week2/blob/main/grant-fine-print/tests/test_integrations.py).

![Previously captured SerpApi search activity](https://dev-to-uploads.s3.us-east-2.amazonaws.com/uploads/articles/o6xc481ebeoenh6xzvjd.png)

![Previously captured SerpApi official-link search queries](https://dev-to-uploads.s3.us-east-2.amazonaws.com/uploads/articles/e94ov1fm5x02sfktv0a8.png)

*Screenshots 14–15 — Existing SerpApi activity captures. They show development-time use, not a new billable call made to validate this submission. Redact account details and keys before publication.*

### Render — the hosted Flask application and read-only proof demo

Render hosts the application at [grant-fine-print.onrender.com](https://grant-fine-print.onrender.com/). The checked-in Blueprint specifies Python 3.11.9, installs the application/PostgreSQL dependencies, and starts Gunicorn with the Flask application factory.

Provider and database secrets are configured outside Git. The Blueprint keeps credential values out of the repository with `sync: false` entries.

**Implementation evidence:** [Render Blueprint](https://github.com/Pritam-mb/week2/blob/main/grant-fine-print/render.yaml), [Flask routes](https://github.com/Pritam-mb/week2/blob/main/grant-fine-print/app/main.py), and [public-proof route tests](https://github.com/Pritam-mb/week2/blob/main/grant-fine-print/tests/test_public_proof.py).

![Previously captured Render web-service deployment dashboard](https://dev-to-uploads.s3.us-east-2.amazonaws.com/uploads/articles/mkdclbb5jm1iwe9z2ln2.png)

*Screenshot 16 — Existing Render dashboard capture. A deployment screenshot documents that captured state; it is not a continuous uptime guarantee or proof of successful model calls.*

During this submission rewrite on **October 19, 2026**, read-only HTTP checks returned **200** for `/`, `/healthz`, `/profiles`, `/evidence`, `/stack`, `/proof/`, and `/proof/hero.png`. These checks establish reachability at that time, not fresh Tinker inference, a successful database write, or the deployed commit identity. An earlier health probe returned 503 before recovering; I am not claiming that operational issue is proven fixed.

## The Evidence: What Was Measured

### 1. Catalog audit: why applicant codes are not enough

The saved **October 17, 2026** catalog contains **528 opportunities**.

| Observation | Count | Interpretation |
|---|---:|---|
| “Others” as the only applicant code | 180/528 (34.1%) | The category alone leaves substantial eligibility detail unresolved. |
| Restriction-language regex hits | 221/528 (41.9%) | A language proxy, not 221 proven disqualifications. |
| Author-labelled permissive-code subgroup containing hard restrictions | 16/26 (61.5%) | Small stratified subgroup; not a population prevalence estimate. |
| Author-labelled Others-only subgroup containing hard restrictions | 12/15 (80.0%) | Small stratified subgroup; not a population prevalence estimate. |

![Historical catalog-audit chart showing Others-only notices and the labelled restriction subgroups](https://dev-to-uploads.s3.us-east-2.amazonaws.com/uploads/articles/rqdxog2945ce77ge9784.png)

*Screenshot 17 — Saved catalog audit. It describes a historical snapshot, not today's open-notice count. The two labelled subgroups are small and single-author.*

[Study output](https://github.com/Pritam-mb/week2/blob/main/grant-fine-print/results/study.json) · [Study implementation](https://github.com/Pritam-mb/week2/blob/main/grant-fine-print/src/study.py)

### 2. Original systems versus the current development replay

The benchmark is **25 unique notices × five constructed profiles = 125 pairs**, labelled by one author. Pairs share notices and profiles; they are not 125 independent observations. Current replay results apply new code to historical extracted conditions after development-set failures were inspected.

“Automatic” means a non-CHECK result. “Correct among automatic” measures agreement with the author's verdict labels, not source-quote correctness or independently established real-world precision.

| System/run | Automatic decisions | Correct among automatic | Human CHECK | Disqualified called eligible |
|---|---:|---:|---:|---:|
| Original code-only | 77/125 | 53/77 | 48/125 | 14/65 |
| Original prompted | 61/125 | 30/61 | 64/125 | 1/65 |
| Original fine-tuned-labelled run | 24/125 | 12/24 | 101/125 | 0/65 |
| Current prompted-cache replay | 5/125 | 5/5 | 120/125 | 0/65 |
| Current fine-tuned-cache replay | 5/125 | 5/5 | 120/125 | 0/65 |

![Historical three-system benchmark chart, not the current source-rule replay](https://dev-to-uploads.s3.us-east-2.amazonaws.com/uploads/articles/qahfou0aexq5rwh2nyqg.png)

*Screenshot 18 — Original saved benchmark visualization. Use the table above and current diagnostic for the hardened matcher's results; this historical screenshot does not display the current five-decision replay.*

The original overall label agreement was **70/125 for code-only**, **47/125 for prompted**, and **29/125 for the fine-tuned-labelled run**. Code-only wins on that metric and on coverage. Original fine-tuned output also wrongly rejected **2/33 eligible pairs**; its source-valid quotes did not make the system reliably correct.

The current fine-tuned-cache replay makes **five rejections and no ELIGIBLE predictions**. Three correct baseline misses; the baseline already rejected the other two. Its exact labelled-sentence agreement is **4/5**, a different measure from the five verdict-label agreements.

**Zero false eligibilities is not a standalone safety result:** always abstaining—or never predicting ELIGIBLE—also achieves zero. The current result is a narrow, traceable catch with very low automation, not a general accuracy breakthrough or a demonstrated fine-tuning win.

### 3. An honest failure: copied text can still miss the decisive rule

For **328026, a TIP Office notice of intent, and the for-profit profile**, the original model-backed output said ELIGIBLE even though the notice said applications were not being accepted.

Its extraction was **not empty**: it copied a mixed applicant list but omitted the application-status restriction. The current matcher returns CHECK because of ambiguous applicant grouping—not because it detected closure. The proof pack includes this case so the successful foreign-organization example does not hide extraction-coverage failures.

### 4. Public artifacts, not just screenshots

| Artifact | What a reader can inspect |
|---|---|
| [Original evidence bundle](https://github.com/Pritam-mb/week2/blob/main/grant-fine-print/results/evidence/EVIDENCE.md) | Saved predictions, labels, source text, constructed profiles, evaluator, examples, and SHA256 manifest. |
| [Current source-rule diagnostic](https://github.com/Pritam-mb/week2/blob/main/grant-fine-print/results/source_semantics/REPLAY.md) | Condition snapshot, current replay, full metrics, verdict changes, and limitations. |
| [Worked-example proof notes](https://github.com/Pritam-mb/week2/blob/main/grant-fine-print/reports/proof_pack/PROOF.md) | All three qualifying catches and the honest failure, with actual quotes and profile facts. |
| [Hosted read-only comparison](https://grant-fine-print.onrender.com/proof/) | Browser-friendly proof page with no model inference. |
| [Proof JSON](https://grant-fine-print.onrender.com/proof/examples.json) and [provenance](https://grant-fine-print.onrender.com/proof/provenance.json) | Machine-readable comparisons and artifact consistency checks. |
| [Hero provenance](https://github.com/Pritam-mb/week2/blob/main/grant-fine-print/docs/images/btod-hero.provenance.json) | Inputs, hashes, renderer, visible scope, and explicit generated-card limitations. |

Hashes establish artifact consistency, not independent authenticity or correctness of the author's labels.

## Code: Reproduce the Saved Evidence Without Keys

[Repository and setup](https://github.com/Pritam-mb/week2/tree/main/grant-fine-print) · [Safe offline instructions](https://github.com/Pritam-mb/week2/blob/main/grant-fine-print/docs/DEMO_OFFLINE.md) · [Production configuration](https://github.com/Pritam-mb/week2/blob/main/grant-fine-print/docs/PRODUCTION_SETUP.md)

```powershell
git clone https://github.com/Pritam-mb/week2.git
cd week2/grant-fine-print

# Python 3.10+: verify original predictions, labels, hashes, and scores.
# No provider keys, site packages, or inference calls required.
python -B -S -m src.evidence_bundle verify --bundle results/evidence

# Replay current rules from saved public conditions into a NEW folder.
# Choose another output path if this one already exists.
python -B -S -m src.matcher_replay --bundle results/evidence --snapshot results/source_semantics/conditions_snapshot.json --output results/replay_check
```

Open `reports/proof_pack/index.html` directly for the offline visual comparison. These commands recompute saved evidence and matcher results; **they do not rerun the original model**.

### Tests and checks

The latest full local suite run passed **1,100 tests** using:

```powershell
# After creating/activating a virtual environment and installing test dependencies:
python -m pip install -e ".[app,test]"
$env:PYTHON_DOTENV_DISABLED = '1'
python -B -m pytest -q -p no:cacheprovider
```

Coverage includes profile creation and validation, explicit mock screening, cards and filters, correction handling, source rules and adversarial cases, extraction/cache parsing, review-reason escaping, evidence/replay verification, hero generation, ingestion adapters, and public-proof allowlisting.

The suite uses controlled fixtures and mocked service boundaries where appropriate. Passing tests do **not** prove live provider accuracy, a production database transaction, customer satisfaction, or that every browser interaction has been manually tested. The original portable evidence verifier also passed, and the public pages listed above were reachable during the rewrite.

## My First User: The Side-Hustle Plan

The intended first user is a **freelance grant writer managing several client profiles**. Instead of selling “AI that finds guaranteed grants,” I would sell a weekly evidence-review workflow: a shortlist, the sentence behind a rejection, and an explicit queue of things that still need judgment.

The proposed price is **$29–$49/month**. This is a hypothesis, not existing revenue. At an illustrative **$39/month** and **$100/hour** value of time, a writer needs **23.4 net minutes saved per month** to break even. With 120/125 current pairs still needing review, I cannot assume the product already meets that bar.

My first-three-customer pilot plan:

1. Recruit three freelance writers with different client domains.
2. Help each create a client profile and establish their existing screening workflow.
3. Compare review correctness and time with and without the evidence cards over four weeks.
4. Record useful catches, missed restrictions, unresolved profile facts, and correction burden.
5. Ask for paid conversion only if the measured benefit justifies it.

There are **no reported external pilot outcomes or paying users yet**. Billing, authenticated client isolation, scheduled weekly delivery, and a production-ready multi-tenant SaaS are not claimed as completed features.

## Why Does Open Innovation Matter?

Grant screening is consequential enough that a confident-looking answer is not sufficient. The writer needs to inspect the source, understand the rule boundary, and challenge the result.

Open model weights make the extractor replaceable. Readable Python makes the deterministic decision path inspectable. Public saved predictions, labelled examples, source snapshots, and reproducible metrics let someone check the demonstrated result without buying provider credits.

The project builds on Qwen, Python, Flask, PostgreSQL, and the sponsor services rather than claiming those components as original inventions. My contribution is the review workflow and its explicit evidence boundaries: extraction is not eligibility, source presence is not semantic correctness, and human review is not hidden behind an accuracy headline.

## Limits and Next Steps

- **Narrow automation:** the current development replay automatically resolves only five of 125 pairs, all as rejections.
- **Small, reused evaluation:** 25 notices, constructed profiles, and single-author labels; no fresh independent holdout or second-labeler validation.
- **Historical identity limits:** legacy cache names do not authenticate model/checkpoint provenance.
- **Incomplete semantics:** foreign-organization exclusions are a demonstrated rule family, not proof of general grant understanding. Cost sharing, prior awards, partnerships, missing facts, and other unsupported constraints still need review.
- **Extraction omissions:** a quote may be valid while a decisive condition is missing, as the notice-of-intent example shows.
- **Source scope:** Grants.gov is evaluated; EU ingestion is a prototype and Canada a placeholder. Notices can change after capture.
- **Operational scope:** recent read-only reachability is not a full live end-to-end check or an uptime promise. Old caches are intentionally cold under the new fingerprint, so live screening may incur fresh provider costs.
- **Product validation:** time savings, pricing, retention, secure multi-user operation, and customer benefit remain to be established.

Next I would correct training-target semantics, collect missing client facts, establish a new notice-level holdout, and measure the workflow with real writers. A stronger model claim should follow that work—not precede it.

## Prize Categories

- **Best Use of Tiger Data:** versioned official snapshots and GIN keyword retrieval, with PostgreSQL persistence support for profiles, corrections, link candidates, and rendered cards. The current local-file UI boundaries are disclosed above.
- **Best Use of Render:** the hosted Flask/Gunicorn application, read-only proof demo, operational health route, and reproducible Blueprint.
- **Best Use of SerpApi:** official Grants.gov link recovery with search snippets kept outside the eligibility evidence path.

**Tinker is documented as an integration and fine-tuning experiment, not a claimed performance win.** The current replay does not establish improvement over the prompted model, so I am not presenting it as evidence of that prize requirement.

---

*Grant Fine Print is a screening aid, not legal or grant advice. Confirm every decision in the current official notice.*

<!-- EDITORIAL CHECKLIST — remove this comment before publishing:
The draft intentionally remains published: false.
Existing images use real, checked URLs; no missing screenshot is disguised as an image.
Replace capture notes SS03, SS04, SS06, SS07, and SS08 with real uploaded screenshots.
Label mock/synthetic screenshots and keep historical benchmark captures labelled historical.
Review console images for credentials, account/connection details, and personal information.
Recheck live links and deployment status near publication; do not trigger paid inference just for screenshots.
Use isolated demo data for profile/correction captures; do not mutate production to stage a demo.
If including an agent-session embed, use an actual authorized share URL; none is invented here.
Check contest deadline/rules before publication. Disclose any required post-deadline commits in README.
-->
