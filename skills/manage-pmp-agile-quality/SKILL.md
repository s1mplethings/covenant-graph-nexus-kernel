---
name: manage-pmp-agile-quality
description: Tailor and operate project management using PMP governance, adaptive or hybrid delivery, built-in quality, bounded enterprise-experience retrieval, and continuous improvement. Use for starting or replanning a project, selecting predictive/agile/hybrid delivery, managing a backlog or iteration, defining quality metrics and evidence, reviewing project status, handling risk or change, closing an iteration, running a retrospective, or applying the same method to CGKN itself.
---

# Manage PMP, Agile, And Quality

Use one tailored method for CGKN development and generated projects. Preserve
stable governance and delivery constraints while delivering the smallest useful
vertical increment and building quality into every increment.

## Run the workflow

1. Read the repository `AGENTS.md` and applicable kernel contracts.
2. Read `references/method.md`.
3. Read `references/quality.md` when defining acceptance, tests, review, or
   release criteria.
4. Read `references/cgkn-integration.md` when working in CGKN or changing a
   generated-project workflow.
5. Inspect or initialize the project-management pack.
6. Retrieve only relevant approved or validated enterprise experience.
7. Select a delivery approach from uncertainty and criticality; do not assume
   Scrum, predictive delivery, or a fixed ceremony set.
8. Order the backlog by value, risk reduction, dependency readiness, and
   learning value.
9. Start one bounded iteration with measurable acceptance, quality metrics,
   interface expectations, and proportionate evidence.
10. Implement and verify the vertical increment.
11. Review the increment, update the backlog, run a retrospective, and record
    an improvement experiment.
12. Promote an enterprise lesson only after evidence and applicability
    boundaries exist.

## Use the deterministic helper

From the CGKN repository, run:

```text
python skills/manage-pmp-agile-quality/scripts/manage_project.py init ...
python skills/manage-pmp-agile-quality/scripts/manage_project.py validate --path ...
python skills/manage-pmp-agile-quality/scripts/manage_project.py retrieve ...
python skills/manage-pmp-agile-quality/scripts/manage_project.py start-iteration ...
python skills/manage-pmp-agile-quality/scripts/manage_project.py close-iteration ...
python skills/manage-pmp-agile-quality/scripts/manage_project.py record-usage ...
python skills/manage-pmp-agile-quality/scripts/manage_project.py render ...
```

Use `init` only for a new management directory. Validate changed management,
iteration, and enterprise-experience JSON before relying on it.

## Preserve boundaries

- Keep workflow and experience states separate from formal evidence status.
- Use only canonical CGKN evidence statuses in `evidence_status`.
- Keep the Codex conversation default on the reviewed provider route.
- Do not create a second generation route or planning authority.
- Keep `local_packager` as the only delivery exit.
- Treat management artifacts and skill output as planning context, not delivery
  evidence.
- Do not expose internal project-management jargon in normal customer replies.
- Tailor artifact depth for small work; never tailor away applicable kernel,
  safety, quality, or delivery constraints.
