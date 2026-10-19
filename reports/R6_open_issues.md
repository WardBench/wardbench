# R6 Open issues

Author: Vadim Nareyko.

## Design choices

- A second Synthea batch (seed 20261020) was added because seed 20261019 alone yielded fewer than 60 eligible patients.
- The false-positive gate lists hits but does not fail the suite (common disorder words appear in neutral sentences).
- The review sheet is capped at 60 rows (one task per template, then a second where space remains).
- Reliability and model runs use `--disable-thinking` and the policy visibility named in each script.

## Uncertain

- Whether `(disorder)`-only required lists match clinical intent for every boundary family.
- How much of the noise floor is LocalAI versus Qwen3 sampling.

## Not done

- The test-split task file is not written yet. Instruction variants 4–5 are reserved for it.

## Files

`templates/`, `wardbench/generate.py`, `wardbench/stats.py`, `wardbench/cohort.py`, `wardbench/world.py`, `wardbench/agents.py`, `scripts/`, `tests/`, `review/`, `tasks/dev.jsonl`, `cohort/dev_manifest.json`, `CHANGELOG.md`, `schema/task.schema.json`.

## Open questions for clinical review

1. Should adversarial tasks whose base is a denied task stay in the headline `attack_induced` denominator?
2. Is age in years acceptable under `deidentified_only`, or should the extract use age bands only?
3. Should registration tasks stay read-only, or also cover a scheduling write?
4. Should psychiatric medication names be forbidden when a PSY Condition is denied?
5. What commitment procedure should run before `tasks/test.jsonl` is written?
