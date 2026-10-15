# Agent-Led Layered Architecture

## 0. Purpose

This document defines the CGKN agent-led layered architecture.

CGKN is agent-led and contract-guarded.

The Lead Agent controls the project run.

Layers do not control the run.

Layers define required handoff artifacts, allowed responsibilities, forbidden responsibilities, and pass gates for agent-led execution.

Modules are capabilities selected by agents.

Artifacts are work records and handoff objects produced by agents.

The contract compiler validates the run; it does not replace the Lead Agent.

The runner executes decisions; it does not own product decisions.

QA evidence verifies delivery; it does not replace product intent.

## 1. Architecture rule

CGKN MUST be understood as:

```text
agent-led
contract-guarded
artifact-traced
module-composed
evidence-delivered
user-revisable
```

The layers in this document are work areas and handoff boundaries. They are not a hardcoded execution script, fixed pipeline template, or replacement for Lead Agent planning.

The Lead Agent MAY revisit a layer, split work across multiple specialist agents, retry a failed route, or choose a different module composition when evidence, policy, or user feedback requires it.

The Lead Agent MUST NOT mark PASS unless required artifacts and PASS gates are satisfied.

## 2. Agent Control Model

### Lead Agent MAY

```text
create project-specific specialist agents
choose modules based on project needs
compose different pipelines for different project types
change the execution route when evidence shows a better route
revise the plan after test failure
request repair and retry
update product_story, mvp_scope, or output_contract when user feedback changes scope
decide whether to continue, repair, mark PASS_WITH_LIMITS, mark BLOCKED, or deliver
```

### Lead Agent MUST

```text
preserve the output_contract
keep required handoff artifacts
respect policy gates
run or attempt validation
collect test evidence
collect visual evidence when required
produce delivery_manifest
mark PASS only when evidence satisfies the contract
```

The Lead Agent owns the execution strategy. Specialist agents own delegated work products. Contracts and layers define what must be preserved, checked, and handed off.

## 3. Dynamic agents and dynamic pipelines

Different user goals MAY create different specialist agents and different execution pipelines.

These examples are dynamic route examples, not fixed templates.

### Image processing GUI tool

Possible specialist agents:

```text
Product Lead
UX Designer
Media Pipeline Engineer
Implementation Engineer
QA Engineer
Delivery Manager
```

Possible route:

```text
customer_intent
  -> output_contract
  -> product_story
  -> media_processing_plan
  -> GUI build
  -> sample image test
  -> screenshot evidence
  -> delivery_manifest
```

### Excel data cleaning tool

Possible specialist agents:

```text
Product Lead
Data Engineer
UX Designer
Implementation Engineer
QA Engineer
Delivery Manager
```

Possible route:

```text
customer_intent
  -> output_contract
  -> product_story
  -> data_schema_plan
  -> sample spreadsheet generation
  -> GUI build
  -> export test
  -> screenshot evidence
  -> delivery_manifest
```

### AI tool frontend

Possible specialist agents:

```text
Product Lead
AI Engineer
UX Designer
Implementation Engineer
QA Engineer
Delivery Manager
```

Possible route:

```text
customer_intent
  -> output_contract
  -> product_story
  -> model/provider decision
  -> UI build
  -> mock/live test depending on policy
  -> screenshot evidence
  -> delivery_manifest
```

The Lead Agent MAY compose other routes when the project type requires different domain agents, modules, tests, or evidence.

## 4. Correct relationship between Agent, Layer, Module, Artifact, Contract, Runner

### Agent

Agent owns decisions and execution strategy.

### Layer

Layer defines working area and handoff boundary.

### Module

Module provides callable capability.

### Artifact

Artifact records agent work and enables handoff.

### Contract

Contract validates boundaries, ports, policy, gates, and evidence requirements.

### Runner

Runner executes project or validation commands.

### QA Evidence

QA Evidence proves whether the generated result works.

### Delivery

Delivery packages result for the user.

The relationship MUST remain:

```text
Agent is the driver.
Contract is the guardrail.
Artifact is the trace.
Module is the capability.
Runner is the executor.
Evidence is the proof.
Delivery is the customer-facing result.
```

## 5. Layer catalog

The seven layers below define required work areas. The Lead Agent MAY adapt route order or revisit layers, but MUST preserve required artifacts and PASS gates for PASS delivery.

## 6. Intake Layer

### Responsibility

The Intake Layer is responsible for understanding the user's goal, inputs, outputs, constraints, assumptions, and unknowns.

### Lead Agent authority in this layer

The Lead Agent MAY ask clarifying questions, infer conservative defaults, record assumptions, and decide whether the request is ready for product design.

### Specialist agents that may participate

```text
Product Lead
Domain Expert
Policy Reviewer
Delivery Manager
```

### Inputs

```text
raw user request
optional files
optional constraints
preferred delivery format
```

### Outputs

```text
customer_intent
```

### Required artifacts

```text
customer_intent
```

### Allowed module types

```text
intake parser
file summarizer
constraint extractor
policy precheck
assumption recorder
```

### PASS Gate

```text
user goal captured
input expectation captured
output expectation captured
constraints captured
assumptions recorded
unknowns recorded
```

### Forbidden responsibilities

FORBIDDEN:

```text
technical stack selection
business project code generation
final architecture decision
final acceptance decision
```

### Handoff contract

The Intake Layer MUST hand off `customer_intent` to product design. The handoff MUST include goal, input, output, constraints, assumptions, and unknowns.

## 7. Product Design Layer

### Responsibility

The Product Design Layer is responsible for `virtual_team_roster`, `product_story`, `mvp_scope`, and `acceptance_implications`.

### Lead Agent authority in this layer

The Lead Agent MAY create different specialist agents according to the project type and MAY revise product artifacts when user feedback changes scope.

### Specialist agents that may participate

```text
Product Lead
UX Designer
Domain Expert
Documentation Lead
Delivery Manager
```

### Inputs

```text
customer_intent
output_contract
```

### Outputs

```text
virtual_team_roster
product_story
mvp_scope
acceptance_implications
```

### Required artifacts

```text
virtual_team_roster
product_story
mvp_scope
acceptance_implications
```

### Allowed module types

```text
role planner
product story generator
MVP boundary planner
acceptance implication mapper
UX journey planner
domain analysis module
```

### PASS Gate

```text
work actions match project type
artifact owners assigned
target user defined
main problem defined
first-run experience defined
MVP boundary defined
non-goals defined
acceptance implications mapped
```

### Forbidden responsibilities

FORBIDDEN:

```text
project code generation
direct final technical implementation decision
runtime execution
test result fabrication
delivery PASS decision without evidence
```

### Handoff contract

The Product Design Layer MUST hand off `virtual_team_roster`, `product_story`, `mvp_scope`, and `acceptance_implications` to engineering planning. Product design MUST NOT be skipped before implementation.

## 8. Engineering Planning Layer

### Responsibility

The Engineering Planning Layer is responsible for `technical_plan`, `build_plan`, `page_flow`, and `data_model` or `state_model`.

### Lead Agent authority in this layer

The Lead Agent MAY select planning specialists, choose module families, revise the plan after QA failure, and choose a different implementation route if evidence shows a better route.

### Specialist agents that may participate

```text
Solution Architect
UX Designer
Data Engineer
AI Engineer
Security Reviewer
Implementation Engineer
```

### Inputs

```text
customer_intent
output_contract
product_story
mvp_scope
acceptance_implications
available modules
policy
```

### Outputs

```text
technical_plan
build_plan
page_flow
data_model or state_model
```

### Required artifacts

```text
technical_plan
build_plan
page_flow
data_model or state_model
```

### Allowed module types

```text
architecture planner
module selector
pipeline composer
UI flow planner
data schema planner
state model planner
environment planner
test strategy planner
```

### PASS Gate

```text
runtime target declared
project structure declared
technology choices declared
page flow declared when UI exists
data_model or state_model declared
environment setup plan declared
test strategy declared
visual evidence strategy declared when required
build tasks mapped to product_story and output_contract
```

### Forbidden responsibilities

FORBIDDEN:

```text
direct generation of the business project
skipping product_story
skipping output_contract
redefining customer-facing success outside output_contract
marking delivery PASS
```

### Handoff contract

The Engineering Planning Layer MUST hand off `technical_plan`, `build_plan`, `page_flow`, and `data_model` or `state_model` to contract compile and build agents. It MUST NOT skip `product_story` or `output_contract`.

## 9. Contract Compile Layer

### Responsibility

The Contract Compile Layer is responsible for `contract_pack`, `compiled_contract_bundle`, `diagnostics`, and `pipeline_composition`.

### Lead Agent authority in this layer

The Lead Agent MAY choose which contract packs and modules to compile, MAY resolve diagnostics, and MAY revise prior artifacts when diagnostics reveal an invalid route.

### Specialist agents that may participate

```text
Contract Compiler
Pipeline Composer
Policy Reviewer
Solution Architect
Lead Agent
```

### Inputs

```text
customer_intent
output_contract
virtual_team_roster
product_story
mvp_scope
technical_plan
build_plan
available modules
artifact schemas
policy
```

### Outputs

```text
contract_pack
compiled_contract_bundle
diagnostics
pipeline_composition
```

### Required artifacts

```text
contract_pack
compiled_contract_bundle
diagnostics
pipeline_composition
```

### Allowed module types

```text
contract compiler
schema validator
port validator
policy checker
pipeline composer
diagnostic reporter
```

### PASS Gate

```text
contract_pack exists
compiled_contract_bundle exists
diagnostics recorded
pipeline_composition recorded
module references valid
artifact references valid
ports valid
flow valid
policy valid
required gates valid
```

### Forbidden responsibilities

FORBIDDEN:

```text
owning the project run
replacing the Lead Agent
making product decisions for the Lead Agent
direct final project code generation
changing user intent without Lead Agent approval
marking delivery PASS without QA evidence
```

### Handoff contract

The Contract Compile Layer MUST hand off `compiled_contract_bundle`, `diagnostics`, and `pipeline_composition` to agent build. The contract compiler is a validator, guardrail, and referee. It is not the controller of the Product Studio run.

## 10. Agent Build Layer

### Responsibility

The Agent Build Layer is responsible for `generated_project`, `implementation_trace`, and `repair_notes`.

### Lead Agent authority in this layer

The Lead Agent MAY assign Builder Agents, request repairs, retry failed builds, change the execution route, or return to planning when evidence shows the build plan is insufficient.

### Specialist agents that may participate

```text
Builder Agent
Implementation Engineer
UX Engineer
Data Engineer
AI Engineer
Media Pipeline Engineer
Security Reviewer
```

### Inputs

```text
output_contract
product_story
mvp_scope
technical_plan
build_plan
compiled_contract_bundle
pipeline_composition
acceptance_matrix or acceptance_implications
```

### Outputs

```text
generated_project
implementation_trace
repair_notes
runtime_notes
```

### Required artifacts

```text
generated_project
implementation_trace
repair_notes, if repairs occurred
runtime_notes
```

### Allowed module types

```text
code generator
file editor
dependency installer
runtime executor
build tool
repair module
static analyzer
formatter
```

### PASS Gate

```text
project files exist
generated_project is mapped to build_plan
implementation_trace exists
runtime start attempted or explicitly blocked
repair_notes exist when repair occurred
known build limitations recorded
```

### Forbidden responsibilities

FORBIDDEN:

```text
redefining success standards
ignoring output_contract
ignoring product_story
ignoring acceptance_matrix
ignoring mvp_scope
claiming PASS without runtime attempt
claiming GUI success without visual evidence when required
```

### Handoff contract

The Agent Build Layer MUST hand off `generated_project`, `implementation_trace`, `runtime_notes`, and any `repair_notes` to QA and evidence. Builder Agent or Implementation Engineer MAY generate code, fix errors, and retry according to `build_plan`, but MUST NOT redefine success.

## 11. QA & Evidence Layer

### Responsibility

The QA & Evidence Layer is responsible for `test_data`, `test_plan`, `test_report`, `screenshots`, `demo_video` or GIF when required, and `visual_evidence`.

### Lead Agent authority in this layer

The Lead Agent MAY accept QA findings, request repair and retry, change route after failure, mark PASS_WITH_LIMITS or BLOCKED, or update product artifacts when user feedback changes scope.

### Specialist agents that may participate

```text
QA Engineer
Evidence Capturer
UX Reviewer
Implementation Engineer
Security Reviewer
Delivery Manager
```

### Inputs

```text
generated_project
runtime_notes
output_contract
product_story
acceptance_matrix or acceptance_implications
technical_plan
```

### Outputs

```text
test_data
test_plan
test_report
screenshots
demo_video or GIF
visual_evidence
known_failures
repair_request, if needed
```

### Required artifacts

```text
test_data
test_plan
test_report
visual_evidence
screenshots, for GUI projects
demo_video or GIF, when required by output_contract
```

### Allowed module types

```text
test data generator
unit test runner
integration test runner
browser runner
screenshot capturer
video or GIF capturer
visual regression checker
QA reporter
```

### PASS Gate

```text
test_data exists
test_plan exists
test_report exists
runtime result recorded
known failures recorded
visual_evidence exists when required
GUI project has screenshot evidence
evidence matches output_contract
```

GUI projects without screenshots MUST NOT pass.

Runs without test data MUST NOT pass.

Runs without test reports MUST NOT pass.

### Forbidden responsibilities

FORBIDDEN:

```text
directly changing product goals without Lead Agent feedback loop
redefining output_contract
claiming tests passed without test_report
claiming GUI delivery without screenshot evidence
hiding known failures
marking final PASS when delivery_manifest is missing
```

### Handoff contract

The QA & Evidence Layer MUST hand off `test_data`, `test_plan`, `test_report`, `visual_evidence`, `known_failures`, and any `repair_request` to the Lead Agent and Delivery Layer. The QA Agent MAY require repair based on evidence, but MUST NOT directly change product intent unless it reports the need to the Lead Agent.

## 12. Delivery Layer

### Responsibility

The Delivery Layer is responsible for `delivery_manifest`, `README`, `user_summary`, `known_limits`, and `revision_entry`.

### Lead Agent authority in this layer

The Lead Agent MAY decide to deliver, request more repair, mark PASS_WITH_LIMITS, mark BLOCKED, or update scope based on user feedback and evidence.

### Specialist agents that may participate

```text
Delivery Manager
Documentation Lead
QA Engineer
Implementation Engineer
Product Lead
```

### Inputs

```text
generated_project
README or startup instructions
test_data
test_report
visual_evidence
project_package
known_limits
revision_entry
output_contract
```

### Outputs

```text
delivery_manifest
README
user_summary
known_limits
revision_entry
project_package
```

### Required artifacts

```text
delivery_manifest
README
user_summary
known_limits
revision_entry
project_package
```

### Allowed module types

```text
packager
README generator
summary generator
evidence bundler
artifact indexer
revision recorder
delivery validator
```

### PASS Gate

```text
runnable_project exists
README or startup instructions exist
test_data exists
test_report exists
visual_evidence exists when required
package exists
known_limits included
revision_entry included
delivery_manifest exists
```

The Delivery Agent MUST NOT mark PASS when `runnable_project`, `test_report`, `visual_evidence`, or package is missing.

### Forbidden responsibilities

FORBIDDEN:

```text
hiding known_limits
marking PASS without runnable_project
marking PASS without test_report
marking PASS without required visual_evidence
marking PASS without package
marking PASS without delivery_manifest
closing the user revision path
```

### Handoff contract

The Delivery Layer MUST hand off `delivery_manifest`, `README`, `user_summary`, `known_limits`, and `revision_entry` to the user. The delivery MUST let the user continue requesting revisions.
