# Why clinician and DPO review must happen before the held-out seal

Author: Vadim Nareyko · WardBench review packet companion (1 page)

**What this is.** A short rationale for reviewing our *simulated* access policies before we freeze the private test pool.  
**What this is not.** Legal advice, a GDPR, HIPAA, or EHDS certificate, or a model scorecard.

## Two kinds of rules in WardBench

| Kind | Rough share of the 120 main tasks | What the agent must respect |
| --- | --- | --- |
| Static role and purpose | Most non-Consent rows | Who is asking (`physician`, `billing`, …) and for which HL7 purpose (`TREAT`, `HPAYMT`, `HRESCH`, …) |
| Dynamic FHIR Consent | 30 tasks | Patient-stateful `Consent` (`active` / `inactive`, `permit` / `deny`, purpose limits, `PSY` mental-health labels) that can change what may be read or said |

Static rules look like a table. Dynamic Consent looks like a **record the agent must find** (or already see in context). Wrong assumptions here silently poison every later score.

## Why this matters empirically (local models, development set)

On `qwen3-14b` with policy in the prompt alone:

- Dynamic Consent tasks: about 18/30 ≈ 60% violations  
- Static role/purpose tasks: about 1/30 ≈ 3% violations  

Prefetching the Consent resource into context cuts dynamic violations from 18/30 to 5/30. Other model families check Consent more often, but then new failure modes appear (for example, refusing a *permitted* twin because the twin inherited research-flavoured wording).

So the hardest part of the benchmark is not “does the model know billing may not quote HbA1c results?” — it is whether our Consent story matches clinical and privacy practice.

## What we ask you to review

You receive:

1. `policy_matrix.md` — the assumed table and numbered assumptions  
2. `review_instructions.md` — how to mark a row  
3. `review_sheet.csv` — up to 60 plain-language tasks (templates, not model answers)

For each row: does the **expected behavior** match how you would want an assistant to behave under the stated simulated policy? Mark `agree` / `disagree` / `unsure` and comment on disagreements.

Please flag: unrealistic asks, too-strict or too-loose expectations, rejected assumptions (especially Consent, `PSY`, research, and related-person).

## Why this must finish before S6b (held-out seal)

After review we may rewrite policies and regenerate tasks. Only then do we:

1. freeze the held-out test pool,  
2. publish a Merkle root commitment,  
3. run models **once** on that sealed set.

If Consent rules are clinically wrong, sealing the held-out set locks in the author’s mistake, not hospital truth. Review now is cheaper than a contaminated public claim later.

## Limits (please keep these in mind)

- All patients are **synthetic** (Synthea).  
- The FHIR server in the benchmark is **intentionally permissive**; the agent must self-enforce.  
- Break-glass, real proxy authorization, and national law are out of scope.  
- Returning the sheet is a research favour, not an endorsement of WardBench as a compliance product.

**Return:** filled `review_sheet.csv` (two review columns) to the address in the cover email. One comment naming a whole broken task family is enough.

Thank you.
