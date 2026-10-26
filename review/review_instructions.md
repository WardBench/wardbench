# Review instructions (one page)

Author: Vadim Nareyko.

Thank you for reviewing WardBench tasks. We are checking whether the **benchmark** is clinically and ethically sensible, not whether a model scored well.

## What you receive

- `policy_matrix.md` — the access policy we assume and a numbered list of assumptions.
- `review_sheet.csv` — about two tasks per template (at most 60 rows). Each row is one task in plain language.

## How to review a row

1. Read the requester role and purpose, the consent description, and the one-line synthetic patient summary.
2. Read the user instruction (what the agent is asked to do).
3. Read the expected behavior and what counts as a violation.
4. Decide whether that expectation matches how your organisation would want an assistant to behave **under the stated simulated policy**.
5. Fill `reviewer_verdict`: `agree`, `disagree`, or `unsure`.
6. Optionally add a short `comment` (especially if you disagree).

## Please do

- Flag instructions that feel unrealistic or unsafe.
- Flag expected behaviors that are too strict, too loose, or ambiguous.
- Flag assumptions in the policy matrix that you reject.
- Remember all patients are synthetic.

## Please do not

- Try to game a model or help it cheat.
- Paste real patient data into comments.
- Treat this sheet as legal advice or as a certification of compliance.

## Returning the sheet

Send back the CSV with the two review columns filled. If a whole family of tasks is wrong, one comment naming the family is enough.
