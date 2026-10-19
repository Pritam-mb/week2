# Grant Fine Print

**Quote-or-abstain grant screening for freelance grant writers.** The application
lives in [`grant-fine-print/`](grant-fine-print/); run application commands there.

The model extracts possible eligibility conditions and source quotes. Python checks
quote provenance and matches supported conditions against client facts; ambiguous,
unsupported, or empty extractions go to human review. A source-valid quote does not
guarantee a correct interpretation. This is a screening aid, not grant/legal advice.

## Start here

- [Application README and setup](grant-fine-print/README.md)
- [Updated submission draft](grant-fine-print/DEVTO_SUBMISSION.md)
- [Portable original-run evidence and three worked examples](grant-fine-print/results/evidence/EVIDENCE.md)
- [Current bounded source-rule diagnostic](grant-fine-print/results/source_semantics/REPLAY.md)
- [All three verified code-only misses](grant-fine-print/reports/proof_pack/PROOF.md)
- [Offline browser comparison](grant-fine-print/reports/proof_pack/index.html)
- [Implementation status and remaining work](grant-fine-print/PROJECT_AUDIT_SUMMARY.md)
- [Deployed app](https://grant-fine-print.onrender.com/)

## Results without spin

The original saved benchmark covers **25 unique Grants.gov notices × five
constructed profiles = 125 pairs**, with single-author labels. The fine-tuned
output called zero of 65 disqualified pairs eligible, but sent **101/125 to CHECK**
and correctly resolved only **12 of 24 automatic decisions**. Code-only has better
overall agreement and less review load. These are development results, not a
production accuracy guarantee or an untouched holdout.

The current bounded source-rule matcher makes **five rejections and 120 CHECKs**
from the historical fine-tuned cache. All five rejections agree with author labels;
three overturn incorrect baseline ELIGIBLE decisions using explicit foreign-organization
exclusions. These all involve the same UK profile and rule family. This is not
broad automation, new inference, a fresh holdout, or a fine-tuning advantage.
The deployed service does not automatically contain uncommitted local changes.

## Verify offline

From the `grant-fine-print` directory, Python 3.10+:

```powershell
python -B -S -m src.evidence_bundle verify --bundle results/evidence
```

This checks artifact hashes, exact pair coverage, metrics, and worked examples.
No API key, training, provider call, or package installation is required. Current
matcher replay instructions and its public condition snapshot are linked above.

Grants.gov is the evaluated source. EU ingestion is a prototype; Canada is a
registered placeholder. Confirm every decision in the current official notice.
