# Acceptance and Evidence Contract

## 0. Purpose

This document defines what counts as a successful Product Studio delivery.

CGKN MUST judge success by usable output and evidence, not by code creation alone.

## 1. Required delivery evidence

A PASS delivery MUST include:

```text
runnable_project
README or startup instructions
test_data
test_report
visual_evidence
project_package
known_limits
revision_entry
```

A delivery MAY include:

```text
demo_video
GIF walkthrough
installer
export samples
API docs
user manual
```

## 2. Evidence artifact map

| Evidence | Required when | Minimum requirement |
| --- | --- | --- |
| `runnable_project` | Always | Project files exist and startup path is documented. |
| `README` | Always | Includes install/start/test instructions and known limits. |
| `test_data` | Always | At least one sample input or fixture. |
| `test_report` | Always | Records what was tested and the result. |
| `visual_evidence` | GUI or visual output projects | At least one screenshot from the generated result. |
| `demo_video` | Interaction-heavy projects | SHOULD be produced when practical. |
| `project_package` | Always | A zip or equivalent package path. |
| `known_limits` | Always | Honest limits, missing pieces, and deferred items. |
| `revision_entry` | Always | How user feedback should continue the project. |

## 3. Acceptance matrix

A Product Studio run SHOULD create `acceptance_matrix` with rows like:

```json
{
  "claim": "User can import a folder and see processed results.",
  "source": "product_story.first_run_experience",
  "required_artifact": "generated_project + visual_evidence",
  "test_method": "run app with sample folder and capture result screen",
  "status": "PASS | PASS_WITH_LIMITS | NOT_EVALUATED | BLOCKED | BLOCKED_PROVIDER | BLOCKED_LOCAL_MODEL | BLOCKED_ENVIRONMENT | NEEDS_REWORK | FAIL"
}
```

Each important product story claim SHOULD map to at least one acceptance row.

## 4. PASS rule

A run can be PASS only when:

```text
output_contract exists
product_story exists
technical_plan exists
generated_project exists
canonical CustomerRuntimeEvidence proves startup, health probe, customer operation, observed result hash, and shutdown
canonical TestExecutionEvidence proves real test execution
test data exists
test report exists
required visual evidence exists
versioned delivery_manifest exists with verified hashes
known limits are recorded
```

## 5. PASS_WITH_LIMITS rule

A run SHOULD be PASS_WITH_LIMITS when the generated project is useful but one or more promised outputs are incomplete.

Examples:

```text
project runs but video evidence is missing
GUI exists but only one screen is implemented
export feature exists but only sample export is verified
README exists but installer is not packaged
```

PASS_WITH_LIMITS MUST include known limits and next actions.

## 6. BLOCKED rule

A run SHOULD be BLOCKED when a required external condition prevents completion.

Examples:

```text
missing credentials
missing required local runtime
unsupported dependency
user-required output format cannot be produced in the current environment
```

BLOCKED MUST include a clear blocker reason and recommended recovery action.

## 7. FAIL rule

A run SHOULD be FAIL when the generated project does not satisfy the required contract and has no usable partial delivery.

Examples:

```text
project files missing
startup path missing
core user journey missing
test evidence missing
delivery package missing
```

## 8. Visual evidence rule

For GUI projects, screenshots are required for PASS.

Screenshots SHOULD show an effective product state: a real user flow after input, changed data, filtered results, generated output, or the requested feature in use. A blank home page, placeholder image, generic summary, or empty shell SHOULD NOT count as sufficient visual evidence for PASS.

The preferred screenshot priority is:

```text
requested feature after interaction
result screen with real or sample data
final UI screen
app home screen
error screen with explanation, only for BLOCKED/PASS_WITH_LIMITS
```

Visual evidence MUST be real browser evidence when a GUI or visual output is required. A static placeholder, generated gradient, README screenshot claim, or file-exists check cannot satisfy PASS.

Visual evidence MUST be linked from `delivery_manifest`.

## 9. Test data rule

Test data MUST be concrete enough for a user or agent to rerun verification.

Examples:

```text
sample images
sample CSV
sample JSON
sample text files
seed database
mock API response
```

A test report without input data SHOULD NOT be PASS.

## 10. Delivery manifest rule

`delivery_manifest` MUST summarize:

```text
what was generated
how to run it
what was tested
where the evidence is
what is incomplete
how to request revision
```

Internal logs alone are not a user-facing delivery.
