import csv
import json
import random
from src.config import load_config
from src.io_utils import load_opportunities

cfg = load_config()
opps = load_opportunities(cfg["cache"]["raw_dir"])
study_ids = {r["opportunity_id"] for r in json.load(open("results/study.json", encoding="utf-8"))["sample"]}

def codes(o):
    return {str(c).strip() for c in o.applicant_types}

candidates = [o for o in opps if o.id not in study_ids and o.eligibility_text.strip()]
others = [o for o in candidates if codes(o) == {"25"}]
permissive = [o for o in candidates if codes(o) != {"25"} and "25" not in codes(o)]
withothers = [o for o in candidates if "25" in codes(o) and codes(o) != {"25"}]

rng = random.Random(20261018)
rng.shuffle(others)
rng.shuffle(permissive)
rng.shuffle(withothers)

picked = others[:9] + permissive[:11] + withothers[:5]
rng.shuffle(picked)
picked = picked[:25]

rows = []
for o in picked:
    rows.append({
        "opportunity_id": o.id,
        "opp_number": o.opp_number,
        "title": o.title,
        "agency": o.agency,
        "applicant_types": "|".join(str(c) for c in o.applicant_types),
    })

with open("data/samples/test_sample.csv", "w", newline="", encoding="utf-8") as fh:
    w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
    w.writeheader()
    w.writerows(rows)

out = []
for i, o in enumerate(picked, 1):
    out.append(
        f"=== [{i}] id={o.id} number={o.opp_number} codes={'|'.join(str(c) for c in o.applicant_types)}\n"
        f"AGENCY: {o.agency}\nTITLE: {o.title}\n"
        f"ELIG: {o.eligibility_text}\n"
        f"SYNOPSIS: {o.synopsis[:1200]}"
    )
open("data/samples/test_review.txt", "w", encoding="utf-8").write("\n\n".join(out))
print("picked", len(picked), "others", sum(1 for o in picked if codes(o)=={'25'}))
