# Built-In Quality

## Plan quality

Define customer-visible fitness, measurable acceptance, interface constraints,
compliance, and process-quality expectations before implementation. A metric
must state its measure, target, and verification method.

## Manage quality

Prevent defects through bounded work, clear interfaces, relevant librarian
context, review, testability, and risk-based design. Audit whether the chosen
process is producing reliable evidence and whether recurring failures indicate
a process defect.

## Control quality

Verify each increment with the applicable layers:

- schema and static validation;
- unit and contract tests;
- integration and dependency tests;
- customer runtime evidence;
- visual or media evidence;
- security, compliance, performance, and accessibility checks.

File existence, generated prose, or an unevaluated checklist is not quality
evidence.

## Improve quality

For significant or recurring defects, record:

```text
observed defect
-> containment
-> root cause
-> corrective action
-> preventive process change
-> verification
-> enterprise-experience candidate
```

Track rework, escaped defects, first-pass acceptance, blocked time, and value
delivery only when those measures help a decision. Avoid vanity metrics and
universal fixed thresholds.

Primary source:

- https://www.pmi.org/learning/library/quality-control-project-management-context-3545
