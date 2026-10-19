---
title: "The applicant code said yes. The grant's fine print said no."
published: false
tags: devchallenge, hf26challenge, opensource, ai
cover_image: https://raw.githubusercontent.com/Pritam-mb/week2/main/grant-fine-print/docs/images/btod-hero.png
---

*This is a submission for the [Hacktoberfest Open-Source AI Challenge Week 2: Side Hustle](https://dev.to/challenges/hacktoberfest-week2-2026-10-12).*

- **For whom:** freelance grant writers screening notices for several clients.
- **What it does:** extracts rules and quotes, then checks what each sentence actually restricts before matching a client.
- **What the replay shows:** **three pairs, one rule family**, corrected after inspecting development-set failures—not a new holdout result.
- **The boundary:** **120/125 pairs still need review**. No new model training or remote inference was run.

[Try the deployed app](https://grant-fine-print.onrender.com/) · [Repository](https://github.com/Pritam-mb/week2/tree/main/grant-fine-print) · [Traceable worked examples](https://github.com/Pritam-mb/week2/blob/main/grant-fine-print/reports/proof_pack/PROOF.md)

## What I Built

**Grant Fine Print is an evidence-first screening assistant, not an autonomous eligibility judge.**

### A real catch: foreign applicants are not foreign components

For **BTOD Centers, opportunity 360446 / PAR-27-024**, the applicant-code baseline marks the constructed UK nonprofit **Meridian Health Trust** eligible. The notice says:

> Non-domestic (non-U.S.) Entities (Foreign Organizations) are not eligible to apply.

It separately allows **foreign components**. Those are different facts: an organization being based abroad is not the same thing as a domestic applicant having a foreign component.

The cached extraction had the right sentence, but classified it as `citizenship_or_residency`. The old matcher abstained because it could not evaluate that type. After inspecting these development-set failures, I added a narrow sentence interpreter: it recognizes an explicit **organizational** exclusion, checks the profile's `us_based: false`, and returns an evidence-backed rejection.

| Same notice and profile | Result |
|---|---|
| Applicant-code baseline | ELIGIBLE |
| Original fine-tuned run (historical cache) | CHECK |
| Same cached conditions + current matcher | NOT_ELIGIBLE |
| Author's reference label | NOT_ELIGIBLE |

**What improved was rule interpretation—not the model weights.** The same path also works with the prompted extraction; this is not a fine-tuning superiority claim. “Fine-tuned” identifies the historical run label: legacy caches cannot confirm the producing checkpoint.

### Another catch, and an honest failure

- **359701, C06 research facilities, same UK profile:** the verified foreign-organization exclusion produces the same baseline ELIGIBLE → current NOT_ELIGIBLE correction. **360541, SPOREs**, supplies the third catch. All three concern **one profile and the same rule family**, not three unrelated capabilities.
- **328026, a TIP Office notice of intent, for-profit profile:** the original model-backed output said ELIGIBLE, although the source says applications are not being accepted. Its extraction was **not empty**: it copied one mixed applicant list and omitted the application-status restriction. The current matcher returns CHECK over ambiguous applicant grouping—not because it detected closure. Extraction coverage remains unfinished.

The [proof pack](https://github.com/Pritam-mb/week2/blob/main/grant-fine-print/reports/proof_pack/PROOF.md) includes all qualifying catches, actual prediction rows, source hashes, profile facts, and an offline browser comparison. It does not silently replace a model's quote with the labelled answer.

## How I Built It

Freelance writers screen for several clients, but applicant-type filters cannot express every restriction in a notice. The saved catalog audit found **180/528** notices using only “Others”; author-labelled subsets contained restrictions in **16/26 permissive-code** and **12/15 Others-only** notices. These are small stratified samples, not population prevalence estimates. The separate **221/528 regex count** measures restriction language, not confirmed disqualifications.

My workflow is:

```text
Official snapshot → model-extracted conditions → source-quote check
              → checks what the sentence restricts → client screening card
```

The source check requires a whitespace-normalized substring. The sentence interpreter supports a small set of organizational-geography and applicant-type rules, including complete lists of alternatives. It does not substitute domicile for citizenship, project location, or component status. Keyword matches alone cannot cause rejection; unresolved rules become **CHECK with an explanation**.

Cards show source links and quoted evidence, support printing, and let a writer record a correction. Extraction is reused across clients; matching remains deterministic. The differentiation is this **auditable review workflow**, not a claim to have invented quote verification or a new ML method. Human overrides are separately recorded.

For a CHECK, the intended benefit is a review starting point: the extracted clause where available, the reason the system could not decide, and the official source. It does not remove that review. Whether those cards save net time remains a user-testing question.

## Demo

![BTOD proof card: applicant codes suggest eligibility but a verified foreign-organization restriction rejects the constructed UK nonprofit](https://raw.githubusercontent.com/Pritam-mb/week2/main/grant-fine-print/docs/images/btod-hero.png)

*Generated from the saved BTOD prediction, profile, and verified quote—not a live application screenshot. The browser comparison is `reports/proof_pack/index.html`; [the proof notes](https://github.com/Pritam-mb/week2/blob/main/grant-fine-print/reports/proof_pack/PROOF.md) show the underlying evidence. [Hosted application](https://grant-fine-print.onrender.com/).*

## What the benchmark supports

The dataset is **25 unique notices × five constructed profiles = 125 pairs**, labelled by one author. It has seen diagnostic reuse. Current results below replay historical conditions through new code; no remote inference or new training was run.

| System/run | Automatic decisions | Correct among automatic | Human CHECK | Disqualified called eligible |
|---|---:|---:|---:|---:|
| Original code-only | 77/125 | 53/77 | 48/125 | 14/65 |
| Original prompted | 61/125 | 30/61 | 64/125 | 1/65 |
| Original fine-tuned run | 24/125 | 12/24 | 101/125 | 0/65 |
| Current prompted-cache replay | 5/125 | 5/5 | 120/125 | 0/65 |
| Current fine-tuned-cache replay | 5/125 | 5/5 | 120/125 | 0/65 |

The five current fine-tuned-cache decisions are all rejections. Three correct code-only misses; the baseline already rejected the other two. **No eligible-labelled pair is automatically cleared.** Five observed agreements do not establish generalized precision, and code-only still wins on coverage and overall label agreement.

**Table note:** zero disqualified-to-eligible errors is trivially achievable by always abstaining—or never saying ELIGIBLE. It is not a stand-alone safety result; read it beside automatic coverage and CHECK counts. Run names reflect historical labels, not authenticated legacy checkpoint provenance.

This is a narrow demonstrated catch, not proof that grant screening is solved. Source-valid quotes can still be misinterpreted, and omitted conditions remain a risk. Fine-tuned replay's exact labelled-sentence agreement is **4/5**: another sentence supports the fifth rejection. Full matrices, quote metrics, historical comparisons, and caveats are in the [current diagnostic](https://github.com/Pritam-mb/week2/blob/main/grant-fine-print/results/source_semantics/REPLAY.md).

### What each sponsor contributes

- **Tinker:** the recorded Qwen/Qwen3.5-4B run trained a rank-16 LoRA on 100 model-assisted examples for three epochs. A later target audit found semantic errors; correcting those and evaluating fresh notices comes before spending another training run. [Recorded training session](https://tinker.thinkingmachines.ai/sessions/146167b6-6a85-54ec-bc00-f0489e3f207d).
- **Tiger Data:** PostgreSQL on Timescale Cloud stores snapshots, manifests, profiles, evaluation runs, and corrections. A GIN index supplies keyword full-text search; correction notes are review inputs, not automatically verified ground truth.
- **SerpApi:** recovers official notice links, accepting HTTPS Grants.gov destinations. Search snippets stay outside the eligibility evidence pipeline.
- **Render:** the Flask/Gunicorn deployment is defined in a Blueprint. Historical mixed-cache timings are not a model-speed benchmark.

## My First User

The intended customer is a freelance grant writer or small consultancy managing several clients. The proposed **$29–$49/month** product is a weekly evidence card that helps a writer review notices—not a guarantee of eligibility.

There are no external pilot outcomes or reported paying users yet. My first-three-customer plan is to recruit three freelance writers, help each create their first client profile, and have them review a weekly card alongside the official notices. The goal is **faster, more accurate review, not automation of 96% of pairs**. At an illustrative $39/month and $100/hour value of time, break-even requires 23.4 net minutes saved; that is a pricing hypothesis, not measured savings. The pilot should measure correctness and time before asking those writers to convert.

## Why Does Open Innovation Matter?

Open model weights make the extractor replaceable; readable Python rules and public evidence make the decision boundary inspectable. A writer or developer can reproduce the saved comparison without a vendor key, inspect the exact rule and quote, and challenge a result instead of trusting a proprietary score. The project builds on Qwen, Python, Flask, and PostgreSQL rather than claiming those components as original work.

## Code

[Project repository and setup](https://github.com/Pritam-mb/week2/tree/main/grant-fine-print) · [Current proof pack](https://github.com/Pritam-mb/week2/blob/main/grant-fine-print/reports/proof_pack/PROOF.md)

### Verify it, then judge it

From `grant-fine-print/`, Python 3.10+:

```powershell
# Verify original saved predictions, labels, hashes, and scores. No API keys.
python -B -S -m src.evidence_bundle verify --bundle results/evidence

# Replay current rules from public cached conditions; use a fresh output folder.
python -B -S -m src.matcher_replay --bundle results/evidence --snapshot results/source_semantics/conditions_snapshot.json --output results/replay_check
```

Verification recomputes scores, **not inference**. Legacy cache names cannot authenticate the producing checkpoint. Labels are single-author; training/evaluation source IDs and hashes do not overlap, but a second labeler and fresh notice-level holdout are still needed. Grants.gov is the evaluated source; EU ingestion is a prototype and Canada a placeholder. Notices change, so users must confirm the current official text.

The next step is not a bigger accuracy headline: it is correcting extraction semantics, collecting missing profile facts, and measuring whether real writers review correctly and faster. That is the product I want to earn the right to sell.

## Prize Categories

- **Best Use of Tiger Data:** searchable official snapshots, client profiles, evaluation records, and corrections in PostgreSQL on Timescale Cloud.
- **Best Use of Render:** the hosted Flask/Gunicorn screening application and reproducible deployment Blueprint.
- **Best Use of SerpApi:** official-link recovery with search snippets kept outside the eligibility evidence boundary.

Tinker is documented as a fine-tuning experiment and lessons learned, not a claimed performance win: the current replay does not establish an advantage over the prompted model.

*Screening aid only. Source: Grants.gov. [Application README](https://github.com/Pritam-mb/week2/tree/main/grant-fine-print) · [Original evidence](https://github.com/Pritam-mb/week2/blob/main/grant-fine-print/results/evidence/EVIDENCE.md) · [Current proof pack](https://github.com/Pritam-mb/week2/blob/main/grant-fine-print/reports/proof_pack/PROOF.md).*
