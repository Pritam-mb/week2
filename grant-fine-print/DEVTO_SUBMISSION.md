---
title: "16 of 26 federal grants that looked open to everyone hid a disqualifier in the fine print"
published: false
tags: devchallenge, hf26challenge, opensource, ai
cover_image: [ADD COVER IMAGE URL - e.g. screenshot of the app's evidence proof sheet or card]
---

*This is a submission for the [Hacktoberfest Open-Source AI Challenge Week 2: Side Hustle](https://dev.to/challenges/hacktoberfest-week2-2026-10-12)*

## The grant that said "everyone" and meant "not you"

Federal notice **P27AS00032** (*Exploring and Enhancing Outdoor and Heritage Tourism in the Chesapeake Bay Watershed*) has almost every applicant box checked: nonprofits, small businesses, universities, and commercial entities. A code filter tells my Kentucky rural health client this is a green light. But the fine print opens with a hard boundary: 

> *"PLEASE NOTE: Projects that take place outside the watershed are not eligible for consideration."*

No code filter will ever catch that sentence.

Grants.gov lets you filter by applicant type, so screening looks solved. It isn't. Over a third of open notices use the catch-all "Others" code and leave the real rules to free text, while others mark every code permissive and bury geographic or organizational restrictions deep in the narrative. For a freelance grant writer managing multiple clients, that means opening each new notice and reading the eligibility section by hand, every week.

I built **Grant Fine Print** to do the first read. It produces a one-page weekly screening card per client that shows which grants to pursue, which to drop, and which need a human read—and it never rules a client out without quoting the exact, character-for-character sentence that does.

---

## What I built

The model never decides whether a client is eligible. The pipeline has four steps:

1. **Pull and cache** the notice, keyed by a hash of its normalized text.
2. **Extract.** A small open model reads the eligibility text once per opportunity and returns structured conditions (organization type, location, size, and status), each paired with an exact quote.
3. **Verify.** Plain Python code checks that each quote is a verbatim substring of the official text snapshot. If it isn't, the condition is dropped.
4. **Match.** Deterministic code compares verified conditions with each client profile.

NOT ELIGIBLE requires a verified quote. Anything else the matcher cannot prove becomes CHECK, accompanied by the exact sentence to read. Because extraction runs once per opportunity and is cached, model cost does not scale with the number of clients. Every card ends with *"Confirm in the original notice,"* reinforcing that this is an auditable screening aid, not legal advice.

```
[ Grants.gov API / Tiger Data Postgres ]
                   │
                   ▼ (Raw Official Text Snapshot + SHA256)
       [ Tinker LoRA: Qwen3.5-4B ]
                   │
                   ▼ (Extracts: {condition, verbatim_quote})
     ╔═════════════════════════════════════════════════════════╗
     ║        DETERMINISTIC PYTHON VERIFIER GATE               ║
     ║  Is `verbatim_quote` an exact byte substring of raw?   ║
     ║                                                         ║
     ║     NO  ──► Dropped! (Zero hallucination tolerance)     ║
     ║     YES ──► Passes to Matcher                           ║
     ╚═════════════════════════════════════════════════════════╝
                   │
                   ▼
     [ Deterministic Python Profile Matcher ]
                   │
                   ├──► LIKELY ELIGIBLE (No disqualifiers found)
                   ├──► NOT ELIGIBLE    (Requires 100% verified quote!)
                   └──► CHECK           (Ambiguous text ──► Human review)
```

### What's in the app: A Visual Walkthrough

#### 1. The Multi-Client Screening Dashboard (`/`)
Freelance grant writers manage multiple clients simultaneously. At the top of the dashboard, client selector tabs let you switch between 5 seeded profiles—or your own custom profiles. The dashboard provides instant sub-12ms full-text keyword search across 528 federal notices powered by PostgreSQL GIN indexes, plus real-time verdict filters (`ALL 528`, `LIKELY ELIGIBLE 117`, `CHECK 264`, `NOT ELIGIBLE 147`).

![Multi-Client Dashboard](APP_DASHBOARD_SCREENSHOT_URL)
*The main screening dashboard showing client profile selector pills, instant full-text search, and verdict breakdown counters.*

#### 2. The Fine-Print Card & Verbatim Disqualifiers (`/card/<profile_id>`)
Each client gets a dedicated, printable one-page proof sheet. For every notice, it renders the agency, closing date, award range, and the official Grants.gov link. When an opportunity is ruled out, it prints a rough-edged rubber stamp (`#stamp-rough` SVG displacement filter) and highlights the exact disqualifying clause with a marker-yellow swipe.

![Image description](https://dev-to-uploads.s3.us-east-2.amazonaws.com/uploads/articles/ollpzirjpdbxlp7qp73i.png)
*A real card for Opportunity **58617** (VA-GRANTS-112508-002, State Veterans Home Construction Grant Program). The notice carries applicant codes for State and Tribal governments, but the fine print explicitly commands: "NO PRIVATE ORGANIZATION, RELIGIOUS, NON-PROFIT, OR INDIVIDUAL IS QUALIFIED TO APPLY." The verified quote is highlighted directly on the card.*

#### 3. Human-in-the-Loop Correction Loop (`POST /correct`)
AI grant screening cannot be a black box. Next to every grant card is an interactive `[ ⚑ This is wrong ]` button. If a grant writer notices an edge case or specialized exception, clicking the button opens an override prompt to change the verdict and submit an explanation note. The correction is immediately saved to the Tiger Data PostgreSQL `corrections` table, applied as a runtime override on subsequent pipeline runs (`apply_corrections=True`), and logged as golden ground truth for future model fine-tuning.

![Human Correction Modal](APP_CORRECTION_SCREENSHOT_URL)
*The human correction interface allowing a grant specialist to override a verdict with audit notes directly into PostgreSQL.*

#### 4. Custom Client Profile Onboarding (`/profiles/new`)
Consultancies can configure new client profiles with specific entity types (501(c)(3) nonprofit, higher education, for-profit corporation, tribal nation, non-US NGO), state jurisdiction, size tier, and domain focus keywords (e.g. "rural health", "clean energy").

![New Client Profile Form](APP_PROFILE_NEW_SCREENSHOT_URL)
*Client profile builder configuring organization criteria and focus keyword filters.*

#### 5. In-App System Diagnostics & Architecture Monitor (`/stack`)
A built-in `/stack` diagnostic page gives grant writers and operators complete transparency into the live system health: active Timescale Cloud database row counts, Tinker LoRA checkpoint status and live inference latency, SerpApi link resolver status, and ingestion adapter settings.

![In-App Stack Diagnostics](APP_STACK_SCREENSHOT_URL)
*Live system health diagnostics in the web app showing connected services, database row counts, and model checkpoints.*

#### 6. Multi-Source Ingestion & Robustness
Ingestion is abstracted via `BaseSourceAdapter` (`src/adapters/`). The pipeline is portal-agnostic: US Federal Grants (`GrantsGovAdapter`) is active, with registered adapter contracts for EU Funding & Tenders and Canada Grants. Downstream fine-tuned extraction, quote verification, and client matching work strictly on normalized dataclasses without portal-specific logic.

Extraction runs on 8 parallel workers (`ThreadPoolExecutor(max_workers=8)` in `src/pipeline.py`), and the repository has **72 passing tests** in pytest.

---

## The stack, and what each sponsor did

### Tiger Data: where everything lives

Snapshots, manifests, profiles, evaluation runs, and corrections live in a Postgres database on Timescale Cloud:

| Table | What it holds |
|---|---|
| `raw_snapshots` | The notice text, eligibility text, and a hash of each pulled notice |
| `manifests` | Each pull: date, new, changed, and duplicate counts |
| `profiles` | Client profiles and focus keywords |
| `eval_runs` | Frozen evaluation results and metrics |
| `corrections` | Human corrections and notes |

```sql
CREATE INDEX idx_raw_snapshots_fts ON raw_snapshots
USING GIN (to_tsvector('english', title || ' ' || coalesce(eligibility_text, '')));
```

Searching 528 notices takes about **12 ms** in the app, measured directly in `app/main.py` via `time.perf_counter()` against `PostgresStore().search(query, limit=20)`. It is keyword full-text search using a GIN index on tsvectors, not vector embeddings. Semantic search with pgvector is the next planned step.

![Image description](https://dev-to-uploads.s3.us-east-2.amazonaws.com/uploads/articles/4kf82j2b6cv6e0lqgkt0.png)

![Image description](https://dev-to-uploads.s3.us-east-2.amazonaws.com/uploads/articles/7kkin1agsl15nstr3jk0.png)

![Image description](https://dev-to-uploads.s3.us-east-2.amazonaws.com/uploads/articles/6jil7mws1c3anr77z9ri.png)

*The active Timescale Cloud console showing the PostgreSQL service, connection pool, and relational tables.*

### Tinker: the fine-tune

I used **Qwen3.5-4B** through Tinker. The fine-tuned version is a LoRA adapter (rank 16, learning rate 0.0002) trained on **100 reviewed examples** for 3 epochs (75 optimizer steps) using Tinker's Python SDK (`create_lora_training_client`). 

Training examples were drafted with model assistance and verified line-by-line by hand to guarantee valid JSON and character-exact quotes. All 25 test opportunities were strictly excluded from the training set, and 338 near-duplicate announcements were removed during preprocessing. The test labels were written by hand and frozen before running any evaluation. On live remote inference over the network, Tinker median latency is 2,268 ms.

[Tinker Training Session Log](https://tinker.thinkingmachines.ai/sessions/146167b6-6a85-54ec-bc00-f0489e3f207d)

![Image description](https://dev-to-uploads.s3.us-east-2.amazonaws.com/uploads/articles/m0yw6svnle6tb7l9j855.png)

![Image description](https://dev-to-uploads.s3.us-east-2.amazonaws.com/uploads/articles/p7tfenhhniy49rkrraep.png)

*Tinker dashboard showing the completed LoRA training run `grant-fine-print-sft` and deployed model checkpoint.*

### SerpApi: government link discovery

Discovery runs from the CLI (`--discover`) and from the app (`POST /discover/<id>`), and every result must be an HTTPS `grants.gov` URL. Search queries are restricted strictly to official government domains (`site:grants.gov`), and web search snippets are barred from entering the eligibility evaluation pipeline—they are used exclusively for navigation.

![Image description](https://dev-to-uploads.s3.us-east-2.amazonaws.com/uploads/articles/o6xc481ebeoenh6xzvjd.png)

![Image description](https://dev-to-uploads.s3.us-east-2.amazonaws.com/uploads/articles/e94ov1fm5x02sfktv0a8.png)

*SerpApi search log showing live queries resolving official Grants.gov notice URLs.*

### Render: production deployment

Deployed live as a web application at [https://grant-fine-print.onrender.com/](https://grant-fine-print.onrender.com/) via Render Blueprint (`render.yaml`), running Gunicorn connected directly to the Tiger Data Timescale PostgreSQL database.

![Image description](https://dev-to-uploads.s3.us-east-2.amazonaws.com/uploads/articles/mkdclbb5jm1iwe9z2ln2.png)

*Render dashboard showing the live web service deployment and build status.*

---

## The design

I wanted the UI to feel like a printed proof sheet on a desk: cream paper with grain, ink-black type, hard-offset shadows (`3px 3px 0 var(--ink)`), no gradients, and no glow.

- **Stamps.** Each verdict is a rubber stamp with a rough edge (`#stamp-rough` SVG displacement filter) that lands with a small thump.
- **Highlighter.** The verified sentence gets a marker-yellow swipe (`.marker-quote`).
- **Proof-sheet details.** Corner paper folds (`.paper-fold-corner`), crop marks on the evidence chart panels, ruled lines on cards, and paper clips and tape strips.
- **Accessibility.** Charts use pattern fills as well as colour, there is a light and dark ink mode, and transitions respect `prefers-reduced-motion` settings.

---

## Who would pay

This is designed as a focused **Side Hustle** for freelance grant writers and boutique consultancies managing 3 to 10 clients. 

Freelance grant writers charge between $75 and $150 per hour. Every Monday morning, they spend hours manually sifting through Grants.gov announcements for their client roster. 

Because extraction runs **once per opportunity** and is cached permanently in Postgres by text hash, model cost does not scale with the number of clients. At **$29 to $49/month**, the tool pays for itself if it saves a writer just 30 minutes a month—while protecting their professional reputation by catching fine-print disqualifiers code filters miss.

---

## The Evidence: Forensic Audit & Benchmark Results

The Evidence suite is live and interactive in the web app under the **Evidence** tab ([https://grant-fine-print.onrender.com/evidence](https://grant-fine-print.onrender.com/evidence)). All benchmarks were evaluated against ground truth hand-labelled by the author before any model was run (git commit `2f90797`).

### 1. The Opportunity Catalog Audit

I pulled **528 open opportunities** on 2026-10-17 and measured the gap before building any model:

| What I counted | Result | Note |
|---|---:|---|
| "Others" as the only applicant code | **180 of 528** (34.1%) | The code tells you nothing |
| Free text with explicit exclusion phrases | **221 of 528** (41.9%) | Regex match for 10 exclusion patterns (e.g., *"not eligible"*, *"only .* may apply"*, *"restricted to"*) |
| Sample: permissive codes, hard disqualifier in the text | **16 of 26** (61.5%) | About 43% to 78% (95% Wilson interval: 42.5% to 77.6%) |
| Sample: "Others" code, hard disqualifier in the text | **12 of 15** (80.0%) | About 55% to 93% (95% Wilson interval: 54.8% to 93.0%) |

![Image description](https://dev-to-uploads.s3.us-east-2.amazonaws.com/uploads/articles/rqdxog2945ce77ge9784.png)

*(Downloadable directly as a PNG from Section 1 of the app's `/evidence` sheet)*

A hard disqualifier is a sentence that says who may not apply, or restricts applicants by location, organisation type, status, or size. The 221 count represents opportunities containing explicit restriction phrases in their `applicantEligibilityDesc` field. In the permissive-code sample, **16 of 26** notices hid a disqualifier that overruled the permissive code. In the "Others" sample, **12 of 15** hid a hard disqualifier. Because sample sizes are small, the Wilson score intervals show the problem is real, even if the exact population rate has wide bounds.

### 2. Three systems on the same frozen test

The test benchmark consists of 5 constructed client profiles evaluated across 25 opportunities, giving **125 pairs**. A "missed grant" means a truly eligible pair was wrongly marked NOT ELIGIBLE. "Wrongly told likely eligible" means a truly disqualified pair was marked LIKELY ELIGIBLE.

| System | Missed grants | Wrongly told "likely eligible" | Human-read share | Exact accuracy | Quote validity |
|---|---:|---:|---:|---:|---:|
| Code-only filter | 0 of 33 (0.0%) | **14 of 65** (21.5%) | 48 of 125 (38.4%) | 70 of 125 (56.0%) | N/A |
| Prompted Qwen | 20 of 33 (60.6%) | 1 of 65 (1.5%) | 64 of 125 (51.2%) | 47 of 125 (37.6%) | 94 of 95 (98.9%) |
| Fine-tuned Qwen | **2 of 33** (6.1%) | **0 of 65** (0.0%) | 101 of 125 (80.8%) | 29 of 125 (23.2%) | **18 of 18** (100.0%) |

![Image description](https://dev-to-uploads.s3.us-east-2.amazonaws.com/uploads/articles/qahfou0aexq5rwh2nyqg.png)

*(Downloadable directly as a PNG from Section 2 of the app's `/evidence` sheet)*

### 3. What the numbers say

- **Why code-only looks like a winner at first:** Code-only has 0 missed grants, the lowest human-read share (48), and the best accuracy (70 of 125). A reader will ask why the model exists. But code-only achieves zero missed grants only because it **never** says NOT ELIGIBLE from free text.
- **The fatal flaw of code-only:** In **14 of 65** cases where a client was strictly disqualified by the text, code-only falsely told them they were **"likely eligible."** That is the 16-of-26 study appearing in production. If a grant writer trusts a code filter, their client spends 15 hours drafting an application for a grant they are barred from winning.
- **What fine-tuning fixed:** Fine-tuned Qwen had **0 of 65** false eligibility errors (0.0%). It never told a disqualified client to apply. Against the prompted base model—which suffered from severe false exclusions, missing 20 of 33 winnable grants (60.6%)—fine-tuning slashed missed grants to just **2 of 33** (6.1%).
- **The trade-off:** The fine-tuned model extracted fewer conditions overall (18 vs 95), but every single one was a valid quote (18 of 18, 100%). When it was uncertain, it safely routed the opportunity to **CHECK** (101 of 125). In grant consulting, sending a card to human review costs 60 seconds; sending a disqualified client after an impossible grant costs thousands of dollars.

### 4. Confusion matrices

Here are the confusion matrices across all 125 test pairs:

```
Code-Only Baseline (Fatal false-positive bias: 14 false eligibilities)
True \ Pred      ELIGIBLE   NOT_ELIGIBLE   CHECK   TOTAL
ELIGIBLE            25            0          8       33
NOT_ELIGIBLE        14           28         23       65
CHECK                5            5         17       27

Prompted Base Qwen (Over-exclusion: 20 missed grants)
True \ Pred      ELIGIBLE   NOT_ELIGIBLE   CHECK   TOTAL
ELIGIBLE             0           20         13       33
NOT_ELIGIBLE         1           30         34       65
CHECK                6            4         17       27

Fine-Tuned Qwen (Zero false eligibilities: 0 of 65, safe routing to CHECK)
True \ Pred      ELIGIBLE   NOT_ELIGIBLE   CHECK   TOTAL
ELIGIBLE             0            2         31       33
NOT_ELIGIBLE         0           12         53       65
CHECK                6            4         17       27
```

---

## Limits

- **Federal grants only:** Currently ingests notices from Grants.gov. State and private foundation grants are not yet included.
- **Small evaluation set:** The 125 test pairs provide clear directional findings, but precision estimates should be interpreted via the reported Wilson intervals.
- **Conservative matching:** Complex rules such as cost sharing, prior award history, and multi-organization partnerships are intentionally routed to CHECK rather than guessed.
- **Notices change:** Amendments occur after the pull date. The platform is an auditable screening tool, not a legal guarantee.

**Next steps:** Expanding the reviewed training set to 500 examples, adding state-level grant parsers, and onboarding our first cohort of freelance grant writing agencies.

---

## Try it

- **Live Deployed App:** [https://grant-fine-print.onrender.com/](https://grant-fine-print.onrender.com/)
- **Repository:** {% github Pritam-mb/week2 %}

```powershell
# Run the local pipeline
python -m src.pull --mock
python -m src.pipeline --backend mock
python -m app.main
```

See the repository README for instructions on running live extraction with Tinker API keys and PostgreSQL.

---

## My agent session

{% agent_session [SESSION LINK] %}

---

## Prize categories

- **Best Use of Tinker:** Demonstrated how LoRA fine-tuning of Qwen3.5-4B turned an aggressive prompted base model (20 of 33 missed grants) into a precision extraction engine (2 of 33 missed grants, 18 of 18 verified quotes, and 0 of 65 false eligibility errors).
- **Best Use of Tiger Data:** Built a live PostgreSQL persistence layer across 5 tables with GIN full-text search indexing, handling snapshot caching, client profiles, and human correction logs at 12ms query latencies.
- **Best Use of SerpApi:** Automated official government link recovery with a strict security and truth boundary that prevents external search snippets from corrupting decision logic.
- **Best Use of Render:** Deployed live as a production web application at [https://grant-fine-print.onrender.com/](https://grant-fine-print.onrender.com/) using a Render Blueprint (`render.yaml`), serving Gunicorn connected to Timescale PostgreSQL with real-time audit cards.

---

*Data from Grants.gov. Base model: Qwen/Qwen3.5-4B (Apache 2.0 license).*
