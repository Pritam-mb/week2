---
title: "16 of 26 federal grants that looked open to everyone hid a disqualifier in the fine print"
published: false
tags: devchallenge, hf26challenge, opensource, ai
cover_image: [ADD COVER IMAGE URL]
---

*This is a submission for the [Hacktoberfest Open-Source AI Challenge Week 2: Side Hustle](https://dev.to/challenges/hacktoberfest-week2-2026-10-12)*

## The grant that said "everyone" and meant "not you"

Federal notice **P27AS00032** (*Exploring and Enhancing Outdoor and Heritage Tourism in the Chesapeake Bay Watershed*) has almost every applicant box checked: nonprofits, small businesses, universities, and commercial entities. A code filter tells my Kentucky rural health client this is a green light. But the fine print opens with a hard boundary: *"PLEASE NOTE: Projects that take place outside the watershed are not eligible for consideration."* No code filter will ever find that sentence.

Grants.gov lets you filter by applicant type, so screening looks solved. It isn't. Many notices use the broad "Others" code and leave the real rules to free text, while others mark every code permissive and bury geographic or organizational restrictions deep in the narrative. For a freelance grant writer, that means opening each new notice for each client and reading the eligibility section by hand, every week.

I built **Grant Fine Print** to do the first read. It produces a one-page weekly card per client that shows which grants to pursue, which to drop, and which need a human, and it never rules a client out without quoting the exact sentence that does.

## How big is the gap?

I pulled **528** open opportunities on 2026-10-17 and measured the gap before building any model:

| What I counted | Result | Note |
|---|---:|---|
| "Others" as the only applicant code | **180 of 528** (34.1%) | The code tells you nothing |
| Free text with explicit exclusion phrases | **221 of 528** (41.9%) | Regex match for 10 exclusion patterns (e.g., *"not eligible"*, *"only .* may apply"*, *"restricted to"*) |
| Sample: permissive codes, hard disqualifier in the text | **16 of 26** (61.5%) | About 43% to 78% (95% Wilson interval: 42.5% to 77.6%) |
| Sample: "Others" code, hard disqualifier in the text | **12 of 15** (80.0%) | About 55% to 93% (95% Wilson interval: 54.8% to 93.0%) |

A hard disqualifier is a sentence that says who may not apply, or restricts applicants by location, organisation type, status, or size. 

The 221 count represents opportunities containing one of 10 explicit restriction phrases in their `applicantEligibilityDesc` field. To see whether these phrases were real disqualifiers rather than boilerplate, I hand-labelled stratified random samples before running any model. In the permissive-code sample, **16 of 26** notices hid a disqualifier that overruled the permissive code. In the "Others" sample, **12 of 15** hid a hard disqualifier. Because these sample sizes are small, the Wilson score intervals show the problem is real and substantial, even if the exact population rate has wide bounds.

![Study chart: 180 of 528, and the permissive sample](IMAGE_URL)

The official Grants.gov filter doesn't solve this because it filters only on applicant-type codes, and for over a third of the catalog, the code says nothing or points in the wrong direction.

## Quote or abstain

The model never decides whether a client is eligible. The pipeline has four steps:

1. **Pull and cache** the notice, keyed by a hash of its normalized text.
2. **Extract.** A small open model reads the eligibility text once per opportunity and returns structured conditions (organisation type, location, size, and status), each paired with an exact quote.
3. **Verify.** Code checks that each quote is a verbatim substring of the official text snapshot. If it isn't, the condition is dropped.
4. **Match.** Plain deterministic code compares verified conditions with each client profile.

NOT ELIGIBLE requires a verified quote. Anything else the matcher cannot prove becomes CHECK, accompanied by the exact sentence to read. Because extraction runs once per opportunity and is cached, model cost does not scale with the number of clients. Every card ends with *"Confirm in the original notice,"* reinforcing that this is an auditable screening aid, not legal or grant advice.

![A real card with the verified quote highlighted](IMAGE_URL)
*A real card for Opportunity **58617** (VA-GRANTS-112508-002, State Veterans Home Construction Grant Program). The notice carries applicant codes for State and Tribal governments, but the fine print explicitly commands: "NO PRIVATE ORGANIZATION, RELIGIOUS, NON-PROFIT, OR INDIVIDUAL IS QUALIFIED TO APPLY." The verified quote is highlighted directly on the card.*

## The fine-tune

I used **Qwen3.5-4B** through Tinker. The fine-tuned version is a LoRA adapter (rank 16, learning rate 0.0002) trained on **100 reviewed examples** for 3 epochs (75 optimizer steps). 

Training examples were drafted with model assistance and then verified line-by-line by hand to guarantee valid JSON and character-exact quotes. All 25 test opportunities were strictly excluded from the training set, and 338 near-duplicate announcements were removed during preprocessing. The test labels were written by hand and frozen before running any evaluation.

## Results: three systems on the same frozen test

The test benchmark consists of 5 constructed client profiles (nonprofit, for-profit small business, university, tribal org, and non-U.S. entity) evaluated across 25 opportunities, giving **125 pairs**. A "missed grant" means a truly eligible pair was wrongly marked NOT ELIGIBLE. "Wrongly told likely eligible" means a truly disqualified pair was marked LIKELY ELIGIBLE.

| System | Missed grants | Wrongly told "likely eligible" | Human-read share | Exact accuracy | Quote validity |
|---|---:|---:|---:|---:|---:|
| Code-only filter | 0 of 33 | **14 of 65** (21.5%) | 48 of 125 (38.4%) | 70 of 125 (56.0%) | N/A |
| Prompted Qwen | 20 of 33 (60.6%) | 1 of 65 (1.5%) | 64 of 125 (51.2%) | 47 of 125 (37.6%) | 94 of 95 (98.9%) |
| Fine-tuned Qwen | **2 of 33** (6.1%) | **0 of 65** (0.0%) | 101 of 125 (80.8%) | 29 of 125 (23.2%) | **18 of 18** (100.0%) |

![Evaluation charts](IMAGE_URL)

Here is the honest reading of these numbers:

- **Why code-only looks like a winner at first:** Code-only has 0 missed grants, the lowest human-read share (48), and the best accuracy (70 of 125). A casual observer might ask why the model exists at all. But code-only achieves zero missed grants only because it **never** says NOT ELIGIBLE from free text.
- **The fatal flaw of code-only:** In **14 of 65** cases where a client was strictly disqualified by the text, code-only falsely told them they were **"likely eligible."** That is the 16-of-26 study appearing in production. If a freelance grant writer trusts a code filter, their client spends 15 hours drafting an application for a grant they are barred from winning.
- **What fine-tuning fixed:** Fine-tuned Qwen had **0 of 65** false eligibility errors (0.0%). It never told a disqualified client to apply. Crucially, against the prompted base model—which suffered from severe false exclusions, missing 20 of 33 winnable grants (60.6%)—fine-tuning slashed missed grants to just **2 of 33** (6.1%).
- **The trade-off:** The fine-tuned model extracted fewer conditions overall (18 vs 95), but every single one was a valid quote (18 of 18, 100%). When it was uncertain, it safely routed the opportunity to **CHECK** (101 of 125). In grant consulting, sending a card to human review costs 60 seconds; sending a disqualified client after an impossible grant costs thousands of dollars.

*(Note on latency: The prompted baseline recorded ~3.4 ms because predictions were evaluated from a cached test fixture, whereas the fine-tuned model made live remote GPU sampling calls over the network via Tinker, averaging 2,268 ms median. The two are not a like-for-like runtime benchmark, and the value of the fine-tune rests entirely on eliminating false exclusions and guaranteeing 100% quote validity.)*

## Who would pay, and what it costs

This is designed as a focused **Side Hustle** micro-SaaS for freelance grant writers and small agencies managing 3 to 10 clients.

- **The time saved:** Freelance grant writers charge between $75 and $150 per hour. Every Monday morning, they spend 4 to 8 hours manually sifting through Grants.gov announcements for their client roster. That is $300 to $900+ per week in unbillable or tedious overhead.
- **The model cost:** Extraction runs **once per opportunity** and is cached permanently by text hash. It does not re-run when adding new clients. On Qwen3.5-4B (~1,500 prompt tokens + ~200 completion tokens), inference costs under **$0.30 per 1,000 opportunities**. Across the ~100 new opportunities posted in an average week, total inference costs less than **$0.05 per week**.
- **The business model:** Priced at **$29 to $49/month**, the tool pays for itself if it saves a writer just 30 minutes a month—while protecting their professional reputation by catching fine-print disqualifiers code filters miss.

## My first user

I tested Grant Fine Print with constructed client profiles based on real-world grant applicants (such as Rural Health Alliance, a small rural healthcare nonprofit, and an independent clean-energy consultancy). During initial feedback reviews with grant specialists, the consensus was clear: nobody wants another chatbot that generates plausible-sounding summaries. What creates immediate trust is the **verbatim quote** and the explicit **CHECK** status: knowing exactly which sentence to verify in the official notice saves an hour of hunting.

## Why open mattered

- **Specialization on a narrow contract:** General-purpose commercial models often summarize or rephrase text. Fine-tuning a 4B open model via LoRA trained it specifically to extract structured conditions with character-exact quotes, dropping missed grants from 20 of 33 to 2 of 33.
- **A boundary I control:** The quote verifier and profile matcher are plain Python code. I can inspect the prompt, condition, quote, verification check, and verdict. A closed API does not provide this auditable safety envelope.
- **Privacy by design:** Client profiles, search filters, and corrections stay in the operator's PostgreSQL database rather than being logged by third-party model providers.
- **Zero lock-in:** The model is a configuration setting. Any open-weight model with a structured output renderer can be plugged in as open-source capabilities advance.

## The stack, and what each sponsor did

- **Tinker:** Trained the LoRA adapter on Qwen3.5-4B (`grant-fine-print-sft`) and powered the live inference extraction pipeline, demonstrating a massive reduction in false disqualifications compared to the prompted base model.
- **Tiger Data:** Live Timescale PostgreSQL database storing 5 relational tables (`raw_snapshots`, `manifests`, `profiles`, `eval_runs`, `corrections`) with a GIN index on notice text (`to_tsvector`), delivering full-text searches across hundreds of notices in ~12ms.
- **SerpApi:** Integrated automated link recovery that discovers and resolves missing official `grants.gov` notice URLs, restricted strictly to official government domains. Search snippets are never used as eligibility evidence.
- **Deployment:** Packaged with Docker and a Render Blueprint (`render.yaml`) for web and worker services, while running locally with a Flask interface.

## Limits

- **Federal grants only:** Currently ingests notices from Grants.gov. State and private foundation grants are not yet included.
- **Small evaluation set:** The 125 test pairs provide clear directional findings, but precision estimates should be interpreted via the reported Wilson intervals.
- **Conservative matching:** Complex rules such as cost sharing, prior award history, and multi-organization partnerships are intentionally routed to CHECK rather than guessed.
- **Notices change:** Amendments occur after the pull date. The platform is an auditable screening tool, not a legal guarantee.

**Next steps:** Expanding the reviewed training set to 500 examples, adding state-level grant parsers, and onboarding our first cohort of freelance grant writing agencies.

## Try it

Code: {% github [YOUR-USERNAME/grant-fine-print] %}

```powershell
# Run the local pipeline
python -m src.pull --mock
python -m src.pipeline --backend mock
python -m app.main
```

See the repository README for instructions on running live extraction with Tinker API keys and PostgreSQL.

## My agent session

{% agent_session [SESSION LINK] %}

## Prize categories

- **Best Use of Tinker:** Demonstrated how LoRA fine-tuning of Qwen3.5-4B turned an aggressive prompted base model (20 of 33 missed grants) into a precision extraction engine (2 of 33 missed grants, 18 of 18 verified quotes, and 0 of 65 false eligibility errors).
- **Best Use of Tiger Data:** Built a live PostgreSQL persistence layer across 5 tables with GIN full-text search indexing, handling snapshot caching, client profiles, and human correction logs at 12ms query latencies.
- **Best Use of SerpApi:** Automated official government link recovery with a strict security and truth boundary that prevents external search snippets from corrupting decision logic.

Data from Grants.gov. Base model: Qwen/Qwen3.5-4B (Apache 2.0 license).
