# Offline demo (zero network, zero keys)

One-page operator note: run the entire Grant Fine Print pipeline with no
network access and no API keys. Good for a smoke test, a CI run, or showing
the moving parts before wiring up a real model.

## Setup

```bash
python -m venv .venv
# PowerShell:  .\.venv\Scripts\Activate.ps1
# bash/zsh:    source .venv/bin/activate
pip install -e ".[app,test]"
```

## Run everything, in order

```bash
python -m src.pull --mock    # offline sample -> data/raw/ + manifest.json
python -m src.study          # results/study.json + data/samples/study_sample.csv
python -m src.pipeline --backend mock  # results/predictions/*.jsonl (+ .meta.json), results/cards/*.html
python -m src.eval           # results/eval.json + results/eval_report.html
```

Then open a card, e.g. `results/cards/p_nonprofit.html` in a browser, and
`results/eval_report.html` for the system comparison. To try the product UI,
run `python -m app.main`, open `http://127.0.0.1:8000`, and follow this
repeatable flow:

1. Click **Load offline sample** on the dashboard.
2. In **Run now**, choose `Rural Health Alliance` (or **All profiles**) and
   choose the `mock` backend explicitly.
3. Click **Run now**, then open the generated card from the run summary. The
   selected backend is carried into the card, filters, and profile switcher.
4. On the card, search for `rural`, switch between the verdict chips, expand a
   source excerpt, and use **This is wrong** / **Record a correction** to test
   the human-review loop.

The preloaded `Rural Health Alliance` profile is a constructed U.S. nonprofit
in Kentucky with rural-health focus keywords. A useful small story is:

- `MOCK-001` **Community Health Outreach Program**: likely eligible because
  the source says, “Eligibility is open to all applicant types, including
  Others.”
- `MOCK-002` **Rural Broadband Expansion Grant**: CHECK because the source
  says, “Only state, county and municipal governments may apply.” The demo
  deliberately asks a human to read this unsupported condition type.
- `MOCK-004` **Small Business Innovation Research**: NOT ELIGIBLE because the
  source restricts the opportunity to small businesses and for-profit
  organizations, with the exact source sentence shown on the card.

For a post, capture the dashboard, the filtered card, the expanded quote, and
the correction form. Describe this as an **offline plumbing demonstration**:
the MockBackend is deterministic and uses verbatim source sentences, but its
metrics are not evidence of real-model quality. Use a real provider before
publishing model-performance claims.

No `GFP_PROVIDER_BASE_URL` / `GFP_API_KEY` is needed. `src.pull --mock` reads
`data/samples/mock_opportunities.json` (or synthesises opportunities if that
file is missing) and makes no HTTP request; `--backend mock` explicitly uses
the **MockBackend** for both model systems.

## What the mock backend guarantees

- **Deterministic:** same input text, same conditions, every time.
- **Verbatim quotes only:** `MockBackend` slices whole sentences out of the
  source text it is handed, so every quote it emits is a verbatim substring
  of the source and always passes `src/verify.py`'s quote check. The mock
  cannot invent a quote.
- **Labelled, not silent:** the fallback is recorded — every predictions file
  in `results/predictions/` has a `<system>.meta.json` sidecar with
  `"backend": "MockBackend"` and `"offline_fallback": true` for the `prompted`
  and `fine_tuned` systems. Never report mock numbers as model results.

## Warning

MockBackend results are **only a pipeline smoke test** — extraction cache,
verifier, matcher, cards, eval metrics and report rendering all work end to
end, but nothing here says anything about how a real model performs. Quote
validity, missed-grant rates and accuracy on mock data measure the plumbing,
not the product. For real numbers, configure a provider (see "Using a real
model" in the README) and re-run `python -m src.pipeline` and
`python -m src.eval`, and check the `.meta.json` files say a real backend.
