# Product Studio Contract

## 0. Contract status

This document is the top-level product contract for CGKN. Formal artifact kinds, schemas, producers, consumers, and statuses are defined in `docs/01_contract_registry.md`.

CGKN is an **Autonomous Project Studio Kernel**. It is not only a contract compiler and not only a code generator. Its product line is to turn a user's goal, input, output, and constraints into a usable project with design artifacts, implementation artifacts, test evidence, and a delivery manifest.

CGKN is agent-led and contract-guarded.

The Lead Agent owns the run. The Product Studio mainline is a required evidence and handoff structure, not a hardcoded script that replaces agent planning.

## 1. Primary user

CGKN serves users who do not want to design the full project path, research the architecture, configure the environment, or manually prove whether the result works.

The user may provide only:

```text
project goal
input description
output requirement
constraints
preferred delivery format
```

CGKN MUST convert that into a project delivery process.

## 2. Required mainline

Every product-generation run MUST preserve this mainline:

```text
customer_intent
  -> output_contract
  -> virtual_team_roster
  -> product_story
  -> mvp_scope
  -> technical_plan
  -> build_plan
  -> generated_project
  -> test_evidence
  -> delivery_manifest
```

A run MUST NOT be marked PASS unless the required artifacts exist and are internally consistent.

The Lead Agent MAY revisit, repair, or adapt the route through these artifacts when evidence, policy, or user feedback requires it. Required artifacts and PASS gates MUST NOT be skipped for PASS.

## 3. Required artifacts

A valid Product Studio run MUST produce these artifacts:

| Artifact | Purpose |
| --- | --- |
| `customer_intent` | Captures the user goal, input, output, constraints, and assumptions. |
| `output_contract` | Freezes the customer-facing expected outputs and delivery formats. |
| `virtual_team_roster` | Declares the generated virtual project team and role responsibilities. |
| `product_story` | Defines the product purpose, target user, user journey, MVP boundary, non-goals, and acceptance implications. |
| `mvp_scope` | Defines the first usable version and explicitly excludes non-MVP scope. |
| `technical_plan` | Defines technology choices, project structure, data flow, runtime target, and environment plan. |
| `build_plan` | Converts the plan into agent-executable implementation tasks. |
| `generated_project` | Contains the runnable project files. |
| `test_evidence` | Contains test data, test results, visual evidence, and known failures. |
| `delivery_manifest` | Versioned manifest produced by `local_packager` after canonical evidence and required review. |

## 4. Product completion rule

A generated project is complete only when CGKN can provide user-visible evidence.

A PASS delivery MUST include:

```text
runnable_project
README or startup instructions
test_data
test_report
visual_evidence, preferably screenshots and optionally video/GIF
source or project package
known_limits
revision_entry
```

If the project cannot be started through canonical CustomerRuntimeEvidence, the run MUST be FAIL, NEEDS_REWORK, or a specific BLOCKED_* status.

If test data is missing, the run MUST NOT be PASS.

If no screenshot or visual evidence exists for a GUI project, the run MUST NOT be PASS.

If no delivery package exists, the run MUST NOT be PASS.

## 5. Virtual team rule

CGKN MUST create a virtual team appropriate to the project type before implementation starts.

The team is not decorative text. Each role MUST own one or more required artifacts.

Default roles:

```text
Product Lead
Solution Architect
UX Designer
Implementation Engineer
QA Engineer
Delivery Manager
```

The virtual team MAY add domain roles when needed, such as Data Engineer, AI Engineer, Game Tools Designer, Security Reviewer, or Documentation Lead.

## 6. Agent role rule

Agents are the main implementers, but they MUST operate under the product contracts.

Agents MAY:

```text
generate code
modify code
repair runtime errors
add tests
create test data
write README files
improve delivery summaries
```

Agents MUST NOT:

```text
skip product_story
skip output_contract
skip acceptance criteria
claim tests passed without test evidence
claim a GUI exists without visual evidence
claim delivery is complete without delivery_manifest
replace the user's requested GUI with a CLI-only project unless it is marked NEEDS_REWORK or PASS_WITH_LIMITS internally and written into known_limits
```

## 7. Output contract priority

The customer-facing output format has priority over internal convenience.

If the user asks for a GUI project, CGKN SHOULD deliver a GUI project.

If the user asks for export files, CGKN MUST either produce export samples or mark the missing output as a blocking issue.

If the user asks for images, screenshots, video, reports, or other evidence, those outputs MUST be represented in `output_contract` and verified in `test_evidence`.

## 8. Forbidden shortcuts

The following shortcuts are FORBIDDEN for a PASS run:

```text
code-only delivery
README-only delivery
test-report without actual test data
mock screenshot claimed as real runtime evidence
successful status without runnable project
successful status without delivery manifest
implementation before product_story and output_contract exist
```

## 9. Revision rule

The first delivery is not the end of the workflow.

A delivery manifest MUST include a revision entry that allows the user to request:

```text
change UI
add feature
change output format
fix runtime bug
rerun tests
regenerate evidence
repackage delivery
```

## 10. Kernel relation

The contract compiler remains important. It validates artifacts, module contracts, flows, policies, and diagnostics.

However, the product studio contract is the top-level product rule. The compiler, pipeline composer, agent builder, QA runner, and delivery packager MUST serve the Lead Agent, this mainline, and the required evidence gates.

The contract compiler MUST act as validator and guardrail. It MUST NOT replace the Lead Agent or own product decisions.
