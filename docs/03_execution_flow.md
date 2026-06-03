# Product Studio Execution Flow

## 0. Purpose

This document defines the required execution stages for CGNK as an Autonomous Project Studio Kernel.

The flow keeps product intent, design, implementation, testing, evidence, and delivery in one traceable mainline.

## 1. Stage list

A Product Studio run MUST use these stages:

```text
S0 Intake
S1 Output Contract Freeze
S2 Virtual Team Formation
S3 Product Story and MVP
S4 Technical Plan
S5 Contract Compile
S6 Agent Build
S7 Environment Run
S8 Test Data and QA
S9 Visual Evidence
S10 Delivery Bundle
S11 User Revision
```

## 2. S0 Intake

Input:

```text
raw user request
optional files
optional constraints
```

Output:

```text
customer_intent
```

Pass gate:

```text
goal captured
input expectation captured
output expectation captured
constraints captured
assumptions recorded
unknowns recorded
```

## 3. S1 Output Contract Freeze

Input:

```text
customer_intent
```

Output:

```text
output_contract
```

Pass gate:

```text
runnable project expectation declared
package format declared
required evidence declared
test data expectation declared
visual evidence expectation declared
requested export formats declared
```

## 4. S2 Virtual Team Formation

Input:

```text
customer_intent
output_contract
```

Output:

```text
virtual_team_roster
```

Pass gate:

```text
required roles exist
artifact owners exist
role responsibilities match project type
```

## 5. S3 Product Story and MVP

Input:

```text
customer_intent
output_contract
virtual_team_roster
```

Output:

```text
product_story
mvp_scope
acceptance_implications
```

Pass gate:

```text
target user defined
main problem defined
first-run experience defined
MVP boundary defined
non-goals defined
story claims mapped to acceptance implications
```

Implementation MUST NOT start before S3 passes.

## 6. S4 Technical Plan

Input:

```text
product_story
mvp_scope
output_contract
```

Output:

```text
technical_plan
```

Pass gate:

```text
runtime target declared
project structure declared
technology choices declared
data or state model declared
GUI or CLI surface declared
environment setup plan declared
test strategy declared
visual evidence strategy declared
```

## 7. S5 Contract Compile

Input:

```text
technical_plan
available modules
artifact schemas
policy
```

Output:

```text
compiled_contract_bundle
diagnostics
```

Pass gate:

```text
module references valid
artifact references valid
ports valid
flow valid
policy valid
required gates valid
```

## 8. S6 Agent Build

Input:

```text
build_plan
compiled_contract_bundle
product_story
output_contract
```

Output:

```text
generated_project
implementation_trace
```

Pass gate:

```text
project files exist
build plan tasks are traced
implementation trace exists
```

Code creation alone is not enough for delivery PASS.

## 9. S7 Environment Run

Input:

```text
generated_project
technical_plan
```

Output:

```text
environment_run_result
runtime_logs
```

Pass gate:

```text
startup attempted
result recorded
runtime logs recorded
clear status recorded
```

A project that cannot start MUST NOT be marked as final PASS.

## 10. S8 Test Data and QA

Input:

```text
generated_project
product_story
acceptance_implications
```

Output:

```text
test_data
test_plan
test_report
```

Pass gate:

```text
test data exists
test plan exists
test result exists
known failures recorded
```

## 11. S9 Visual Evidence

Input:

```text
environment_run_result
test_report
output_contract
```

Output:

```text
visual_evidence
screenshots
optional demo video or GIF
```

Pass gate:

```text
required screenshots exist
visual evidence paths recorded
visual evidence matches output_contract
```

For GUI projects, at least one final UI screenshot is required for PASS.

## 12. S10 Delivery Bundle

Input:

```text
generated_project
test_data
test_report
visual_evidence
known_limits
```

Output:

```text
delivery_bundle
user_summary
project_package
```

Pass gate:

```text
package exists
README or startup instructions exist
test evidence included
visual evidence included
known limits included
revision entry included
```

## 13. S11 User Revision

Input:

```text
user_feedback
delivery_bundle
current artifacts
```

Output:

```text
revision_plan
updated artifacts
```

Pass gate:

```text
feedback classified
affected artifacts identified
next build or review action recorded
```

## 14. Required status vocabulary

Each stage MUST report one of:

```text
PASS
PARTIAL
BLOCKED
FAIL
SKIPPED_WITH_REASON
```

A required stage with `SKIPPED_WITH_REASON` MUST make the whole delivery PARTIAL or BLOCKED unless another artifact proves the requirement was satisfied.
