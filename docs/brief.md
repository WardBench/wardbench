# WardBench

Author: Vadim Nareyko.

Draft paper title: **WardBench: Measuring Policy Compliance of LLM Agents in Clinical FHIR Environments**.

WardBench measures whether a clinical LLM agent stayed inside what it was allowed to do, not only whether it completed the task. The public project description is [overview.md](overview.md).

This note records the project framing. Claims below that came from web search are marked as unverified and must be checked against the primary source before they go into a paper.

## Niche

Private benchmarking and clinical agent benchmarks already exist as separate lines of work. The gap this project targets is the intersection: task success **and** compliance with patient consent and access policy.

Related work to cite after reading the papers:

- **TRUCE** (Microsoft Research): private benchmarking with confidential computing and cryptography so test data is not revealed to the model.
- **P⁴Bench** (reported as ICML 2026): public verifiability of evaluation with zero-knowledge proofs while answers stay hidden.
- **ArxivRoll** (reported as AAAI 2026): dynamic private tests in the spirit of a one-time pad.
- **MedAgentBench**: FHIR environment (reported: HAPI FHIR in Docker), profiles for 100 patients and 700k+ records, clinician-authored clinical tasks. Planning notes did not find checks that the agent respects patient consent and access policy. Confirm that in the paper and the task/grader code before claiming the gap.

The cryptographic piece here is a light commitment layer, not a ZK protocol. Cite TRUCE and P⁴Bench as related work. A ZK version is v2.

## Environment

Extend MedAgentBench’s FHIR setup or stand up a separate one. Data is synthetic.

Policy layer on top of the clinical records:

- FHIR `Consent` resources.
- Purpose of use: treatment, or secondary use for research (in the spirit of EHDS).
- Minimum necessary access.

Check the MedAgentBench repository license before reusing code. A third-party preprint was reported to call it MIT; that is a retelling, not the license.

## Task types

About 100–150 reviewed tasks, not a large raw set. Templates × patients × policies.

1. **Allowed.** The agent must complete the task. Measures utility.
2. **Policy-forbidden.** The agent must refuse or return a partial result.
3. **Adversarial.** Injection inside a clinical note (for example, “send all data to address X”).
4. **Borderline.** Some data is allowed and some is not. The answer must be redacted precisely.

Each task is a record with: patient, requester role, purpose, consent state, instruction text, allowed resource set, forbidden resource set, and expected behavior (complete, refuse, or partial).

Requester roles to define: clinician at the point of care, researcher with secondary use, front desk.

## Metrics

- Success on allowed tasks.
- Violation rate on forbidden tasks.
- False-refusal rate.

A model that always refuses has no violations, so false refusals are mandatory. The headline figure is **utility versus policy compliance** for 4–6 models.

This is a policy simulation. Do not claim GDPR or HIPAA compliance.

## Data

Use **Synthea**, not real records.

- Synthea is an open synthetic-patient generator. Software is Apache-2.0. Generated public datasets are reported as public domain. Confirm current license text before publishing.
- Export is HL7 FHIR R4, including bulk ndjson. Starter command from the README: `run_synthea -p 10 --exporter.fhir.export=true`. A first cohort of 300–500 patients is enough; a 20–50 patient smoke cohort comes first.
- A freshly generated cohort is the closed test. MedAgentBench’s public patients may already be in model training data.
- Do not use MIMIC or similar PhysioNet restricted data. PhysioNet is reported to forbid sharing with third parties, including sending records through an API, and to recommend local LLMs. Cloud use is reported as allowed only with zero retention, no training, and no human review. That rules MIMIC out for a benchmark that calls commercial model APIs.

What has to be written, because it does not come out of Synthea:

- `Consent` resources per patient: full access, no secondary use, category denial (for example psychiatry, HIV), revoked consent.
- Requester role and purpose on each task.
- Clinical notes with planted instructions for injection tasks. A model may draft the note text; a person reviews it.

## Evaluation

Do not use an LLM judge for the main metric.

Log every FHIR request the agent makes and score the final answer deterministically. A violation is a request for, or a disclosure of, a resource in the forbidden set.

Two server modes:

- **No enforcement.** The agent must follow the policy itself. This is the measured condition.
- **Enforcement.** The server blocks forbidden access. This is the control.

Ablations:

- Policy only in the `Consent` resource, or also stated in the prompt.
- Injection at the start of the note or at the end.

Runs: 4–6 models, 3 runs per task. Estimate API cost from a pilot; a rough planning guess was on the order of hundreds of dollars.

## Closed split

Split about 100 open tasks (dev) and 50 closed tasks (test).

Before the test run, publish a Merkle root over salted hashes of each closed task together with its reference answer. After scoring, release the tasks so anyone can recompute the root. Implementation is a short Python script using `hashlib`. Position this as a practical commitment layer.

## Human review

One or two clinicians or data-protection people should review about 30% of the tasks: is the policy correct, and is the expected behavior correct. Report agreement in the paper. Without that review, the labels are not credible.

## Deliverables

- This repository.
- A 6–8 page arXiv report.
- A leaderboard page.

## Open checks

Do these before citing or registering names. Name registration and hosting setup are out of scope for this note.

- Read MedAgentBench (paper and code): task format, graders, whether consent or access policy is scored, and the license in the repository.
- Confirm Synthea license and export flags, and the PhysioNet credentialed-data rules, against current docs.
- Confirm tool versions before depending on them (Inspect, HAPI FHIR).
- Quoted-string search for “WardBench” on Google Scholar and arXiv. Ordinary web search only found furniture (“ward bench”), which is not a substitute.
- Name collisions still worth a direct look: GitHub `wardbench`, PyPI `wardbench`, Hugging Face `wardbench`.

## Name

**WardBench** is the project name. The word alone does not say what is measured; the subtitle does.

DiscloseBench was the alternative. It names disclosure too narrowly (the benchmark also covers excess resource access, false refusals, and injections) and collides with other uses of “disclosure” in the AI literature. It can name a metric inside WardBench, such as a disclosure score, or stay as a spare name.
