# PMP, Agile, And Quality Self-Hosting

## Purpose

CGNK uses the same project-management method that it offers to generated
projects. The method is a tailored hybrid: stable governance and delivery
constraints surround short, value-oriented implementation iterations with
quality built into every increment.

This capability is a support and planning layer. It does not create a second
generation route, replace the reviewed provider route, or create another
delivery exit.

## Three concurrent loops

### Value loop

```text
product vision
-> ordered backlog
-> smallest useful vertical increment
-> implementation and demonstration
-> stakeholder feedback
-> backlog reorder
```

Backlog order considers customer value, risk reduction, dependency readiness,
and learning value. A large architecture-only batch is not an increment unless
it provides independently verifiable risk reduction.

### Quality loop

```text
quality requirements and metrics
-> increment quality plan
-> prevention and assurance activities
-> automated and runtime controls
-> defect and root-cause analysis
-> corrective action and process improvement
```

Quality is planned before implementation and checked during implementation.
Testing at the end cannot replace measurable acceptance criteria, interface
validation, review, runtime evidence, or continuous improvement.

### Governance loop

```text
outcomes and constraints
-> current evidence
-> risk, issue, compliance, and change assessment
-> decision
-> plan/backlog/document update
```

Governance preserves value, legal and policy compliance, resource constraints,
formal CGNK evidence rules, and the canonical delivery route. It must not turn
normal backlog refinement into heavyweight change control.

## Tailoring

Choose a delivery approach from project context:

| Context | Preferred approach |
| --- | --- |
| Stable requirement and stable technology | predictive or light hybrid |
| Evolving requirement or meaningful technical uncertainty | hybrid |
| High change, discovery, and frequent stakeholder feedback | adaptive/agile |
| Safety, regulatory, or irreversible delivery constraints | hybrid with stronger governance and quality controls |

Every approach still requires value measures, explicit quality requirements,
risk ownership, evidence-backed status, and closure criteria. Artifact volume,
iteration length, ceremonies, and approval depth are tailored.

## Required support artifacts

`CGKNAdaptiveProjectManagementPack` is the current project-management snapshot.
It contains the vision, selected way of working, governance boundaries, ordered
backlog, quality-management plan, risks, iteration references, and improvement
backlog.

`CGKNAdaptiveIteration` is one inspectable increment. It binds a goal and
selected backlog items to acceptance criteria, quality metrics, dependency and
interface expectations, review evidence, and retrospective outcomes.

`CGKNEnterpriseExperiencePack` is the reusable organizational experience
store. Approved experience must include its situation, action, outcome,
applicability boundaries, and evidence. Retrieval must remain bounded and must
record a usage receipt.

These are management artifacts, not formal delivery evidence. Their
`workflow_state` and `experience_state` fields must never be interpreted as
`EvidenceStatus`.

## CGNK self-hosting rule

For non-trivial CGNK work:

1. Read the active management pack.
2. Tailor the way of working to the change.
3. Select or add a value-bearing backlog item.
4. Start an iteration with measurable acceptance and quality metrics.
5. Implement the smallest useful vertical increment.
6. Run proportionate unit, contract, integration, and runtime checks.
7. Close the iteration with evidence, review, and a retrospective.
8. Add an enterprise-experience candidate only when a reusable lesson has
   concrete evidence and applicability boundaries.

Small and urgent fixes may use a shortened iteration record, but they may not
skip applicable kernel rules or claim unsupported evidence.

## Generated-project rule

The approved `manage-pmp-agile-quality` skill applies the same method to
generated projects. It supplies tailored management context to the existing
provider component and leaf generation route. It does not own provider
selection, candidate materialization, formal acceptance, packaging, or public
delivery.

## Quality model

Each backlog item must define outcome or acceptance criteria and measurable
quality metrics before it enters an iteration. The project quality plan covers:

- product fitness and customer-visible behavior;
- interface and integration correctness;
- implementation maintainability;
- test, runtime, visual, media, security, and compliance evidence as applicable;
- process quality, including rework, escaped defects, blocked time, and
  first-pass acceptance;
- the cost and proportionality of prevention, appraisal, failure, and rework.

The definition of done is a minimum shared boundary. Iteration-specific quality
metrics may strengthen it but may not weaken kernel or delivery contracts.

## Enterprise learning

Experience moves through:

```text
candidate -> validated -> approved -> retired
```

This is an experience workflow, not an evidence status. Validation requires
evidence. Approval requires review and a stated applicability boundary. Each
use records whether the practice was applied and its observed result so that an
apparently successful practice can be strengthened, narrowed, superseded, or
retired.
