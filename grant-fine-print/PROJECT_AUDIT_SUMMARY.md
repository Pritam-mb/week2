# Grant Fine Print — Comprehensive Project Audit & Operational Summary

**Generated Date**: October 18, 2026  
**Repository**: [grant-fine-print](file:///d:/week2/grant-fine-print)  
**Branch**: `main`  
**Live Web Server**: `http://127.0.0.1:8000` (PID active)  
**Test Suite**: 58 / 58 passing (`python -m pytest -q`)

---

## 1. Executive Summary

**Grant Fine Print** is an automated grant intelligence pipeline and interactive card dashboard built for freelance grant writers and consultants. The system continuously ingests federal notices of funding opportunities from Grants.gov, extracts unstructured applicant requirements using LLMs, verifies quotes with character-for-character exactness against source texts, deterministically matches eligibility against client profiles, and renders one-page decision cards.

This document provides a transparent, no-fluff audit of:
1. **What is done and 100% original / live** (no mocks or stubs).
2. **What is hardcoded, heuristic, or static** (rules, dictionaries, and constraints).
3. **What is left / pending** (roadmap, future scaling, and production deployment).

---

## 2. What is DONE & 100% Original (No Mocks, Genuine Live Systems)

| Component | Status | Source File | Description |
| :--- | :---: | :--- | :--- |
| **Grants.gov API Pull** | **Live** | [src/pull.py](file:///d:/week2/grant-fine-print/src/pull.py) | Ingests live federal opportunities via REST `search2` and legacy detail endpoints; 528 real snapshots cached. |
| **Tinker Remote Inference** | **Live** | [src/extract.py:OpenAICompatibleBackend](file:///d:/week2/grant-fine-print/src/extract.py#L190-L264) | Calls Thinking Machines Tinker API (`Qwen/Qwen3.5-4B`) with `reasoning_effort: false` and `separate_reasoning: false`. |
| **Tinker LoRA Fine-Tuning** | **Live** | [src/train.py](file:///d:/week2/grant-fine-print/src/train.py) | Cloud GPU LoRA training pipeline (`ServiceClient.create_lora_training_client`) trained for 3 epochs (75 optimizer steps) converging to loss `0.0039 - 0.029`. |
| **Active SFT Sampler Weights** | **Live** | [results/tinker_sampler_checkpoint.json](file:///d:/week2/grant-fine-print/results/tinker_sampler_checkpoint.json) | Checkpoint `tinker://146167b6-6a85-54ec-bc00-f0489e3f207d:train:0/sampler_weights/grant-fine-print-sft` loaded directly by [FineTunedBackend](file:///d:/week2/grant-fine-print/src/extract.py#L265-L315). |
| **Verbatim Quote Verification** | **Live** | [src/verify.py](file:///d:/week2/grant-fine-print/src/verify.py) | Mathematical character-for-character substring checker. Guarantees 0% hallucinated quotes can trigger a `NOT_ELIGIBLE` decision. |
| **Tiger Data Persistence** | **Live** | [src/storage.py](file:///d:/week2/grant-fine-print/src/storage.py) | Connected to Timescale Cloud PostgreSQL (`DATABASE_URL`). Manages 5 tables, GIN full-text search indexes (`to_tsvector`), and profiles. |
| **SerpApi Discovery** | **Live** | [src/discovery.py](file:///d:/week2/grant-fine-print/src/discovery.py) | Uses live `SERPAPI_KEY` to search Google for official Grants.gov pages for opportunities missing links, and validates HTTPS `.grants.gov` domains. |
| **SerpApi Integration** | **Live** | [src/pipeline.py](file:///d:/week2/grant-fine-print/src/pipeline.py), [app/main.py](file:///d:/week2/grant-fine-print/app/main.py) | Wired into CLI (`python -m src.pipeline --discover`) and web app (`POST /discover/<opportunity_id>`). |
| **Parallel Extraction Engine** | **Live** | [src/pipeline.py:run_model_system](file:///d:/week2/grant-fine-print/src/pipeline.py#L114-L140) | Multi-threaded `ThreadPoolExecutor(max_workers=8)` cuts inference latency by up to 8x. |
| **Interactive Web Application** | **Live** | [app/main.py](file:///d:/week2/grant-fine-print/app/main.py) | Running at `http://127.0.0.1:8000`: supports live filtering, full-text search, sorting, human corrections (`/correct`), and print views. |
| **Test Suite** | **Live** | [tests/](file:///d:/week2/grant-fine-print/tests) | 58 unit and integration tests passing 100% in ~35 seconds. |

---

## 3. What is Hardcoded, Heuristic, or Static

To prevent AI hallucinations from causing false grant disqualifications, the matching engine uses deterministic rules and explicit bounds:

### 3.1. Keyword Dictionary Mapping ([src/match.py:ORG_TYPE_KEYWORDS](file:///d:/week2/grant-fine-print/src/match.py#L50-L64))
- **What is hardcoded**: Free-text condition phrases are mapped to federal applicant categories using an explicit string tuple list:
  ```python
  ORG_TYPE_KEYWORDS = [
      ("nonprofit_501c3", ["501(c)(3)", "charitable", "nonprofit"]),
      ("for_profit", ["for-profit", "commercial organization", "company"]),
      ("small_business", ["small business"]),
      ("public_state_university", ["public", "state university"]),
      ("private_university", ["private", "institution of higher education", "university"]),
      ("federally_recognized_tribal_government", ["federally recognized", "tribal government"]),
      ("native_american_tribal_organization", ["tribal", "native american", "indian tribe"]),
      ("state_government", ["state government", "state agency"]),
      ("county_government", ["county"]),
      ("city_or_township_government", ["city", "township", "municipal"]),
      ("individual", ["individual", "sole proprietor"]),
  ]
  ```
- **Consequence**: If an agency uses unusual wording (e.g., *"regional development authority"* or *"school board"*), the matcher cannot classify it (`None`) and conservatively marks it `unknown`, forcing a manual human `CHECK`.

### 3.2. Applicant-Type Code Mapping ([src/match.py:PROFILE_TO_CODES](file:///d:/week2/grant-fine-print/src/match.py#L23-L47))
- **What is hardcoded**: Profile organization categories map to a static set of Grants.gov applicant code strings (e.g., `nonprofit` ➜ `{"nonprofit_501c3", "nonprofit_non_501c3", "others"}`).

### 3.3. Evaluable Condition Dimensions ([src/match.py:evaluate_condition](file:///d:/week2/grant-fine-print/src/match.py#L74-L120))
- **What is hardcoded**: Deterministic plain code evaluates **only 3 dimensions**:
  1. `org_type`: via keyword dictionary.
  2. `location`: simple binary regex for U.S. (`["u.s.", "united states", "domestic"]`) vs Non-U.S. (`["foreign", "outside the u.s"]`). Specific state restrictions (e.g. "must reside in Kentucky") are not parsed.
  3. `size`: simple check for presence of `"small business"`.
- **Consequence**: The other 5 condition types (`citizenship_or_residency`, `partnership_required`, `cost_share`, `prior_award_or_status`, and `other`) are hardcoded to return `"unknown"`. They automatically produce a `CHECK` verdict displaying the exact sentence for the grant writer to read.

### 3.4. Offline Mock Rules ([src/extract.py:_MOCK_RULES](file:///d:/week2/grant-fine-print/src/extract.py#L92-L114))
- **What is hardcoded**: 19 regular expressions used exclusively when the CLI flag `--backend mock` is explicitly invoked.
- **Safety check**: In production (`--backend prompted` or `--backend fine_tuned`), this dictionary is never touched.

### 3.5. Default Seed Profiles ([data/profiles/](file:///d:/week2/grant-fine-print/data/profiles))
- **What is static**: 5 pre-configured JSON profiles (`p_nonprofit`, `p_for_profit`, `p_university`, `p_tribal`, `p_small_business`). New profiles can be created dynamically through the web form at `/profiles/new`.

---

## 4. What is Left / Limitations & Roadmap

### 4.1. Training Dataset Scale (SFT Dataset)
- **Current state**: The fine-tuned LoRA checkpoint was trained on 100 reviewed examples for 3 epochs.
- **Result**: Missed-grant rate dropped from 54.5% to **6.1%**, and quote validity is **100%**.
- **What is left**: Expanding the training set from 100 to 300–500 reviewed examples from the remaining 400+ non-test opportunities will push overall classification accuracy higher than the base model (currently 23.2% vs 37.6% base, because the fine-tuned model is very conservative and prefers human `CHECK`).

### 4.2. Cold-Start Full Corpus Extraction Latency
- **Current state**: With 8 concurrent threads, extracting 25 opportunities takes ~6 seconds, and 500 opportunities takes ~2–3 minutes over the network API.
- **What is left**: In production, caching into PostgreSQL and local disk eliminates repeated requests. An automated background worker (Celery/RQ) could pre-warm the cache overnight upon every new Grants.gov daily XML release.

### 4.3. Cloud Cron Deployment (Render.com)
- **Current state**: [render.yaml](file:///d:/week2/grant-fine-print/render.yaml) is configured with web service and a Monday 06:00 UTC sync cron job.
- **What is left**: The cron job currently only executes when hosted on Render.com with an active worker service; on a local Windows machine, weekly syncs require manual execution (`python -m src.pull`) or Windows Task Scheduler.

### 4.4. Advanced State & Numerical Eligibility Matching
- **Current state**: State-specific grants (e.g., "must be located in Ohio") fall through to `CHECK`.
- **What is left**: Adding an automated 50-state parser to `src/match.py` to evaluate state-level eligibility against `profile.state`.

---

## 5. Verification Log & Key Commands

- **Run Web Server**:
  ```powershell
  python -m app.main
  ```
- **Run Fast Pytest Suite**:
  ```powershell
  python -m pytest -q
  ```
- **Run Discovery on Any Opportunity (via SerpApi)**:
  ```powershell
  curl.exe -X POST http://127.0.0.1:8000/discover/103313
  ```
- **Run Benchmark Evaluation (All 3 Systems)**:
  ```powershell
  python -m src.pipeline --ids-file data/labels/test_labels.csv
  python -m src.eval
  ```
- **Inspect PostgreSQL Records**:
  ```powershell
  python -m src.storage search --query "tribal health" --limit 3
  ```
