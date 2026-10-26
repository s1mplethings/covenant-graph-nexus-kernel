# Failure Appendix

## Internal holdout

- B0: 14 failures, primarily required-answer abstention/term mismatch.
- B1: 26 failures; one Qwen transport timeout and subsequent frozen aggregate
  output-budget exhaustion produced unknown usage for later tasks.
- B2: 57 failures; flat context induced widespread abstention and term mismatch.
- B3: 23 failures, primarily required-answer abstention/term mismatch.
- B4: 24 failures, primarily required-answer abstention/term mismatch.

Schema selection and hidden-gold isolation remained intact. Failed calls with
unknown usage are represented by null token/cost fields, never zero.

## Public benchmark preflight

- CRAG: environment blocked by LFS dataset/storage requirements.
- LongMemEval-V2: environment blocked by Python/model/data requirements.
- BFCL V4: environment blocked by the official Python 3.10 environment.
- TUA-Bench: environment blocked because Docker daemon was unavailable.
- SWE-bench Pro V2: environment blocked because Docker daemon was unavailable.

## Release-gate issue repaired

An A/B equivalence test exposed volatile duration and receipt metadata in
downstream dependency prompts. The production prompt boundary now projects only
stable semantic facts. Three focused A/B runs, the application/experiment
boundary, full pytest, and all kernel profiles passed after the change.
