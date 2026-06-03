# Agent Operating Contract

## 0. Purpose

This document defines how coding agents operate inside CGNK Product Studio runs.

Agents are primary implementers, but they are not allowed to redefine success. Success is defined by `output_contract`, `product_story`, `acceptance_matrix`, `test_evidence`, and `delivery_bundle`.

## 1. Agent authority

Agents MAY:

```text
generate project files
modify project files
repair runtime errors
create or update tests
create test fixtures
write README files
create delivery summaries
propose technical changes
```

Agents SHOULD explain implementation decisions through artifacts rather than free-form status text.

## 2. Required inputs

Before implementation, an agent SHOULD receive:

```text
customer_intent
output_contract
virtual_team_roster
product_story
mvp_scope
technical_plan
build_plan
acceptance_matrix or acceptance_implications
```

If these inputs are missing, the agent MUST either request the missing artifact or create a conservative draft and mark it as an assumption.

## 3. Required outputs

Agent build work SHOULD produce:

```text
generated_project
implementation_trace
updated_build_plan
runtime_notes
repair_notes, if repairs occurred
```

QA or delivery agents SHOULD produce:

```text
test_data
test_report
visual_evidence
delivery_bundle
known_limits
revision_entry
```

## 4. Implementation rule

An agent MUST implement the MVP described by `product_story` and `mvp_scope` before expanding optional features.

If the user asks for a GUI, the agent SHOULD implement a GUI or mark the mismatch as PARTIAL.

If the user asks for a specific output format, the agent MUST either produce it or record why it is missing.

## 5. Testing rule

Agents MUST NOT mark implementation complete only because files were written.

Completion requires evidence from:

```text
environment run result
test data
test report
visual evidence when required
delivery bundle
```

## 6. Repair rule

When runtime or tests fail, agents SHOULD repair based on observed evidence.

A repair note SHOULD include:

```text
failure observed
likely cause
files changed
validation attempted
remaining risk
```

## 7. User revision rule

When the user requests changes, the agent MUST classify the request as one or more of:

```text
UI change
feature addition
output format change
runtime bug
test update
evidence update
delivery repackaging
scope change
```

A scope change SHOULD update `product_story`, `mvp_scope`, or `output_contract` before implementation resumes.

## 8. Forbidden behavior

Agents MUST NOT:

```text
ignore output_contract
ignore product_story
skip MVP and build unrelated features
claim tests passed without test_report
claim GUI success without screenshot evidence when screenshots are required
claim delivery complete without delivery_bundle
hide known limits
replace requested output format without recording the change
use internal logs as the only user-facing delivery
```

## 9. Status rule

Agent status MUST use:

```text
PASS
PARTIAL
BLOCKED
FAIL
```

A PASS status MUST cite the artifacts that prove completion.

A PARTIAL status MUST list missing outputs and next actions.

A BLOCKED status MUST list blocker reason and recovery action.

A FAIL status MUST list failed contract conditions.

## 10. Artifact-first communication

Agents SHOULD communicate through artifacts first:

```text
plan artifact
build artifact
test artifact
evidence artifact
delivery artifact
```

Human-readable summaries are required, but they MUST be backed by artifacts.

## 11. Safety and policy boundary

Agents MUST respect policy declarations for:

```text
network use
provider use
filesystem writes
external commands
secret handling
risk level
```

If a required action violates policy, the agent MUST record a BLOCKED status instead of silently bypassing the policy.
