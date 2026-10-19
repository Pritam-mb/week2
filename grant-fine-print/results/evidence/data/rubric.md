# Labelling rubric (written before labelling)

Written before any model output was seen, per the freeze rule in section 8.2.

## Hard disqualifier

A sentence that says who may **not** apply, or that restricts applicants by
location, organisation type, status or size. Examples:
- "Only U.S.-based organizations are eligible."
- "For-profit organizations are not eligible to apply."
- "Applicants must be located in [state/region]."
- "Foreign entities are excluded."

## Verdicts

- **ELIGIBLE**: the profile clearly meets every stated applicant requirement.
  There is no stated requirement the profile clearly fails, and no requirement
  that depends on facts absent from the profile.
- **NOT_ELIGIBLE**: at least one stated requirement or exclusion clearly rules
  the profile out. Mark the exact disqualifying sentence.
- **CHECK**: a requirement depends on facts not in the profile, or the text is
  genuinely ambiguous, or the requirement cannot be evaluated from the
  information given.

## When unsure

Label CHECK and note why. Never guess to make the numbers look better.

## Profiles

Constructed profiles, disclosed as constructed:

| id | type | notes |
|---|---|---|
| p_nonprofit | nonprofit 501(c)(3) | rural health, US-based |
| p_forprofit | for-profit small business | US-based |
| p_university | public state university | US-based |
| p_tribal | tribal organisation | US-based |
| p_nonus | non-US organisation | not US-based |

## Test opportunities

Selected at random with a recorded seed, stratified so some have the "Others"
applicant type code and some have permissive codes.

## Disqualifying sentence

For every NOT_ELIGIBLE pair, record the verbatim sentence that rules the
profile out, so quote correctness can be measured.
