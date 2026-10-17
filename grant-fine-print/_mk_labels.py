import csv
from src.config import load_config
from src.io_utils import load_opportunities

cfg = load_config()
opps = {o.id: o for o in load_opportunities(cfg["cache"]["raw_dir"])}

FOREIGN_NIH_ORG = "Non-domestic (non-U.S.) Entities (Foreign Organizations) are not eligible to apply."
FOREIGN_NIH_INST = "Non-domestic (non-U.S.) Entities (Foreign Institutions) are not eligible to apply."
NSF_ONLY = "Proposals may only be submitted by the following:"

# decisions[id] = {profile: (verdict, disqualifying_sentence, note)}
D = {
"328026": {p: ("CHECK", "", "notice of intent: no applications are being accepted at this time; no applicant requirements stated")
    for p in ["p_nonprofit","p_forprofit","p_university","p_tribal","p_nonus"]},
"360753": {
    "p_nonprofit": ("ELIGIBLE","","only foreign entities are excluded; profile is US-based"),
    "p_forprofit": ("ELIGIBLE","","only foreign entities are excluded; profile is US-based"),
    "p_university": ("ELIGIBLE","","only foreign entities are excluded; profile is US-based"),
    "p_tribal": ("ELIGIBLE","","only foreign entities are excluded; profile is US-based"),
    "p_nonus": ("NOT_ELIGIBLE", FOREIGN_NIH_INST, "foreign institutions are explicitly excluded"),
},
"58617": {
    "p_nonprofit": ("NOT_ELIGIBLE", "NO PRIVATE ORGANIZATION, RELIGIOUS, NON-PROFIT, OR INDIVIDUAL IS QUALIFIED TO APPLY.", "non-profits are explicitly not qualified"),
    "p_forprofit": ("NOT_ELIGIBLE", "NO PRIVATE ORGANIZATION, RELIGIOUS, NON-PROFIT, OR INDIVIDUAL IS QUALIFIED TO APPLY.", "private organizations are explicitly not qualified"),
    "p_university": ("NOT_ELIGIBLE", "ONLY STATE AND TRIBAL GOVERNMENTS MAY APPLY.", "only state and tribal governments may apply; a public university is not the applicant"),
    "p_tribal": ("NOT_ELIGIBLE", "ONLY STATE AND TRIBAL GOVERNMENTS MAY APPLY.", "the applicant must be the tribal government, not a tribal organisation"),
    "p_nonus": ("NOT_ELIGIBLE", "ONLY STATE AND TRIBAL GOVERNMENTS MAY APPLY.", "only US state/tribal governments may apply"),
},
"363985": {
    "p_nonprofit": ("ELIGIBLE","","private nonprofit organizations are eligible and no other requirement fails"),
    "p_forprofit": ("NOT_ELIGIBLE","the eligible applicants are State, local and tribal governments, other public entities, educational institutions, and private nonprofit organizations","for-profit organizations are not in the eligible list"),
    "p_university": ("ELIGIBLE","","educational institutions are eligible"),
    "p_tribal": ("ELIGIBLE","","tribal governments are in the eligible list"),
    "p_nonus": ("NOT_ELIGIBLE","This program does not provide funding to foreign entities or for projects conducted outside the United States.","foreign entities are excluded"),
},
"364012": {
    "p_nonprofit": ("NOT_ELIGIBLE","Only Water Resources Research Institutes established under the Water Resources Research Act of 1984 are eligible to apply.","not a Water Resources Research Institute"),
    "p_forprofit": ("NOT_ELIGIBLE","Only Water Resources Research Institutes established under the Water Resources Research Act of 1984 are eligible to apply.","not a Water Resources Research Institute"),
    "p_university": ("CHECK","","a university may host a Water Resources Research Institute; cannot tell from the profile"),
    "p_tribal": ("NOT_ELIGIBLE","Only Water Resources Research Institutes established under the Water Resources Research Act of 1984 are eligible to apply.","not a Water Resources Research Institute"),
    "p_nonus": ("NOT_ELIGIBLE","Only Water Resources Research Institutes established under the Water Resources Research Act of 1984 are eligible to apply.","not a US Water Resources Research Institute"),
},
"347680": {
    "p_nonprofit": ("ELIGIBLE","","non-profit non-academic organisations may apply"),
    "p_forprofit": ("NOT_ELIGIBLE", NSF_ONLY, "proposals may only come from non-profits or IHEs"),
    "p_university": ("ELIGIBLE","","IHEs may apply"),
    "p_tribal": ("NOT_ELIGIBLE", NSF_ONLY, "Tribal Nations are not among the allowed submitters"),
    "p_nonus": ("NOT_ELIGIBLE","similar organizations located in the U.S.","submitters must be located in the U.S."),
},
"360541": {p: ("ELIGIBLE","","only foreign entities are excluded; profile is US-based")
    for p in ["p_nonprofit","p_forprofit","p_university","p_tribal"]} | {
    "p_nonus": ("NOT_ELIGIBLE", "Non-domestic (non-U.S.) Entities (Foreign Organization) are not eligible to apply.", "foreign organizations are explicitly excluded"),
},
"345938": {
    "p_nonprofit": ("ELIGIBLE","","non-profit institutions are eligible"),
    "p_forprofit": ("ELIGIBLE","","industry (for-profit) is eligible"),
    "p_university": ("ELIGIBLE","","institutions of higher education are eligible"),
    "p_tribal": ("NOT_ELIGIBLE","Eligible applicants include: industry, non-profit institutions, institutions of higher education, state and/or local educational agencies, or consortia of such institutions and/or industry.","tribal organisations are not in the eligible list"),
    "p_nonus": ("NOT_ELIGIBLE","Foreign entities will not be considered.","foreign entities are excluded"),
},
"363764": {p: ("CHECK","","eligibility is stated only for the PI (engineering department, no recent EEC funding); depends on facts absent from the profile")
    for p in ["p_nonprofit","p_forprofit","p_university","p_tribal","p_nonus"]},
"351947": {
    "p_nonprofit": ("ELIGIBLE","","non-profit non-academic organisations may apply"),
    "p_forprofit": ("NOT_ELIGIBLE", NSF_ONLY, "proposals may only come from non-profits, IHEs or Tribal Nations"),
    "p_university": ("ELIGIBLE","","IHEs may apply"),
    "p_tribal": ("CHECK","","eligible submitters include Tribal Nations; the profile is a tribal organisation, not clearly the recognised tribal government"),
    "p_nonus": ("NOT_ELIGIBLE","similar organizations located in the U.S.","submitters must be located in the U.S."),
},
"358934": {p: ("ELIGIBLE","","only foreign entities are excluded; profile is US-based")
    for p in ["p_nonprofit","p_forprofit","p_university","p_tribal"]} | {
    "p_nonus": ("NOT_ELIGIBLE", FOREIGN_NIH_ORG, "foreign organizations are explicitly excluded"),
},
"359861": {
    "p_nonprofit": ("CHECK","","requires enrolling undergraduates and NIH RPG funding under $50M/yr; not in the profile"),
    "p_forprofit": ("NOT_ELIGIBLE","All applications must include a baccalaureate degree-granting organization.","a for-profit small business is not a baccalaureate degree-granting organization"),
    "p_university": ("CHECK","","NIH RPG funding history under $50M/yr is not in the profile"),
    "p_tribal": ("CHECK","","requires enrolling undergraduates and NIH RPG funding history; not in the profile"),
    "p_nonus": ("NOT_ELIGIBLE", FOREIGN_NIH_INST, "foreign institutions are explicitly excluded"),
},
"357836": {
    "p_nonprofit": ("NOT_ELIGIBLE","","only public universities (code 06) are eligible; no free-text exclusion sentence"),
    "p_forprofit": ("NOT_ELIGIBLE","","only public universities (code 06) are eligible"),
    "p_university": ("ELIGIBLE","","public universities are eligible and only foreign entities are excluded"),
    "p_tribal": ("NOT_ELIGIBLE","","only public universities (code 06) are eligible"),
    "p_nonus": ("NOT_ELIGIBLE", FOREIGN_NIH_INST, "foreign institutions are explicitly excluded"),
},
"356309": {
    "p_nonprofit": ("NOT_ELIGIBLE","fund federally recognized American Indian/Alaska Native (AI/AN) Tribes, tribal colleges or universities, Tribal health programs, or Tribal organizations","only tribal entities may apply"),
    "p_forprofit": ("NOT_ELIGIBLE","fund federally recognized American Indian/Alaska Native (AI/AN) Tribes, tribal colleges or universities, Tribal health programs, or Tribal organizations","only tribal entities may apply"),
    "p_university": ("NOT_ELIGIBLE","fund federally recognized American Indian/Alaska Native (AI/AN) Tribes, tribal colleges or universities, Tribal health programs, or Tribal organizations","a public state university is not a tribal entity"),
    "p_tribal": ("ELIGIBLE","","Tribal organisations are eligible"),
    "p_nonus": ("NOT_ELIGIBLE", "Non-domestic (non-U.S.) Entities (Foreign Institutions) are not eligible to apply", "foreign institutions are explicitly excluded"),
},
"359701": {
    "p_nonprofit": ("ELIGIBLE","","only foreign entities are excluded; profile is US-based"),
    "p_forprofit": ("NOT_ELIGIBLE","","only nonprofits and universities (codes 06,12,13,20) are eligible"),
    "p_university": ("ELIGIBLE","","only foreign entities are excluded; profile is US-based"),
    "p_tribal": ("NOT_ELIGIBLE","","only nonprofits and universities (codes 06,12,13,20) are eligible"),
    "p_nonus": ("NOT_ELIGIBLE", FOREIGN_NIH_ORG, "foreign organizations are explicitly excluded"),
},
"360446": {p: ("ELIGIBLE","","only foreign entities are excluded; profile is US-based")
    for p in ["p_nonprofit","p_forprofit","p_university","p_tribal"]} | {
    "p_nonus": ("NOT_ELIGIBLE", FOREIGN_NIH_ORG, "foreign organizations are explicitly excluded"),
},
"342747": {p: ("NOT_ELIGIBLE","Fellowships are awarded to individuals.","the applicant is an individual, not an organisation")
    for p in ["p_nonprofit","p_forprofit","p_university","p_tribal"]} | {
    "p_nonus": ("NOT_ELIGIBLE","The proposer is a citizen, national, or lawful permanent resident","must be a US citizen/national/permanent resident"),
},
"362480": {
    "p_nonprofit": ("NOT_ELIGIBLE","Only the Lead State Agency (or Agencies) as determined by the Governor of each Highlands State may be the applicant for funding under the Highlands Conservation Act Grant Program.","only the designated Lead State Agency may apply"),
    "p_forprofit": ("NOT_ELIGIBLE","Only the Lead State Agency (or Agencies) as determined by the Governor of each Highlands State may be the applicant for funding under the Highlands Conservation Act Grant Program.","only the designated Lead State Agency may apply"),
    "p_university": ("NOT_ELIGIBLE","Only the Lead State Agency (or Agencies) as determined by the Governor of each Highlands State may be the applicant for funding under the Highlands Conservation Act Grant Program.","only the designated Lead State Agency may apply"),
    "p_tribal": ("NOT_ELIGIBLE","Only the Lead State Agency (or Agencies) as determined by the Governor of each Highlands State may be the applicant for funding under the Highlands Conservation Act Grant Program.","only the designated Lead State Agency may apply"),
    "p_nonus": ("NOT_ELIGIBLE","Only the Lead State Agency (or Agencies) as determined by the Governor of each Highlands State may be the applicant for funding under the Highlands Conservation Act Grant Program.","only a US Lead State Agency may apply"),
},
"360627": {p: ("NOT_ELIGIBLE","NIDDK requests a Single Source competition for the Continuation of the Physiology of the Weight Reduced State (POWERS) Study at the University of Pittsburgh.","single-source to the current recipient only")
    for p in ["p_nonprofit","p_forprofit","p_university","p_tribal","p_nonus"]},
"359676": {p: ("CHECK","","eligibility depends on holding an ACGME-recognised fellowship program; not in the profile")
    for p in ["p_nonprofit","p_forprofit","p_university","p_tribal","p_nonus"]},
"358411": {
    "p_nonprofit": ("NOT_ELIGIBLE","","only govs/universities/tribal (codes 00-07,11,20) are eligible"),
    "p_forprofit": ("NOT_ELIGIBLE","","only govs/universities/tribal (codes 00-07,11,20) are eligible"),
    "p_university": ("CHECK","","requires ISO 17025 accreditation and a valid 20.88 agreement; not in the profile"),
    "p_tribal": ("CHECK","","requires ISO 17025 accreditation and a valid 20.88 agreement; not in the profile"),
    "p_nonus": ("NOT_ELIGIBLE","","only US domestic entities are in the eligible codes"),
},
"359671": {
    "p_nonprofit": ("NOT_ELIGIBLE","Only United States small business concerns (SBCs), as defined by the Small Business Administration (SBA)(sbir.gov/apply) are eligible to submit applications for this opportunity.","only US small business concerns may apply"),
    "p_forprofit": ("ELIGIBLE","","a US small business concern is eligible; foreign entities excluded but profile is US-based"),
    "p_university": ("NOT_ELIGIBLE","Only United States small business concerns (SBCs), as defined by the Small Business Administration (SBA)(sbir.gov/apply) are eligible to submit applications for this opportunity.","only US small business concerns may apply"),
    "p_tribal": ("NOT_ELIGIBLE","Only United States small business concerns (SBCs), as defined by the Small Business Administration (SBA)(sbir.gov/apply) are eligible to submit applications for this opportunity.","only US small business concerns may apply"),
    "p_nonus": ("NOT_ELIGIBLE","Only United States small business concerns (SBCs), as defined by the Small Business Administration (SBA)(sbir.gov/apply) are eligible to submit applications for this opportunity.","only US small business concerns may apply"),
},
"363912": {p: ("CHECK","","eligibility points to APS instructions not present in the text; cannot evaluate")
    for p in ["p_nonprofit","p_forprofit","p_university","p_tribal","p_nonus"]},
"363906": {p: ("NOT_ELIGIBLE","This MURI competition is open only to, and proposals are to be submitted only by, U.S. institutions of higher education (universities) with degree-granting programs in science and/or engineering, including DoW institutions of higher education.","only US universities may submit")
    for p in ["p_nonprofit","p_forprofit","p_tribal","p_nonus"]} | {
    "p_university": ("ELIGIBLE","","US universities are the eligible submitters"),
},
"359650": {
    "p_nonprofit": ("NOT_ELIGIBLE","eligible applicants are limited to accredited institutes of higher education.","only accredited IHEs may apply"),
    "p_forprofit": ("NOT_ELIGIBLE","eligible applicants are limited to accredited institutes of higher education.","only accredited IHEs may apply"),
    "p_university": ("ELIGIBLE","","an accredited institute of higher education is eligible"),
    "p_tribal": ("NOT_ELIGIBLE","eligible applicants are limited to accredited institutes of higher education.","only accredited IHEs may apply"),
    "p_nonus": ("NOT_ELIGIBLE", "Non-domestic (non-U.S.) Entities (Foreign Organization) are not eligible to apply.", "foreign organizations are explicitly excluded"),
},
}

PROFILE_ORDER = ["p_nonprofit","p_forprofit","p_university","p_tribal","p_nonus"]
rows = []
problems = []
for oid, byp in D.items():
    opp = opps[oid]
    src = opp.source_text
    for pid in PROFILE_ORDER:
        verdict, sentence, note = byp[pid]
        if sentence and sentence not in src:
            problems.append((oid, pid, sentence))
        rows.append({
            "opportunity_id": oid,
            "profile_id": pid,
            "true_verdict": verdict,
            "disqualifying_sentence": sentence,
            "source_text": src,
            "rubric_note": note,
        })

if problems:
    print("WARNING: %d sentences not found verbatim in source_text:" % len(problems))
    for oid, pid, s in problems:
        print("  ", oid, pid, repr(s[:80]))

with open("data/labels/test_labels.csv", "w", newline="", encoding="utf-8") as fh:
    w = csv.DictWriter(fh, fieldnames=["opportunity_id","profile_id","true_verdict","disqualifying_sentence","source_text","rubric_note"])
    w.writeheader()
    w.writerows(rows)

from collections import Counter
print("wrote", len(rows), "pairs;", Counter(r["true_verdict"] for r in rows))
