# Role-Driven Validation Pass 2

Pass 2 is a support-only, deterministic cross-project experiment. It does not
change the CGKN generation route, formal evidence, packaging, delivery, or
customer project data. It answers whether role labels themselves improve
defect discovery once business-boundary exploration is controlled.

## Experimental design

Three structurally different executable projects are tested at one Git commit:

- ORBIT-360: dependency graph, persisted JSON state, resume, and repair.
- CGKN Agent Kit: project initialization, local configuration, and secrets.
- Artifact-driven Todo: typed files, lineage, cache reuse, and invalidation.

Each project receives a bounded known defect in a detached worktree. The
ORBIT-360 defect was previously confirmed; the other two are controlled seeds
applied only inside disposable worktrees. Production data and running services
are never touched.

The three arms receive five discovery actions per project:

- A: ordinary tests plus the documented primary path.
- B: a role-labelled business-boundary task.
- C: exactly B's executable boundary task without the role metadata.

B and C have identical task text, channels, action budgets, public evidence,
project variants, and independent oracles. Their matched result isolates the
effect of deterministic role metadata. This is not an LLM autonomous-testing
claim: the run makes zero model calls and records model cost and token budget
as zero.

## Blindness and evidence

The executor receives only public requirements, normal documentation, public
CLI/Python interfaces, and legal test materials. Public plans and execution
records exclude tests, hidden defects, injection targets, injection receipts,
and independent oracle text. A forbidden-value scan runs before scoring and
again after fresh-workspace reproduction. Only after both phases finish is the
hidden baseline, including injection receipts, written under `hidden/`.

Every candidate finding is evaluated by a deterministic oracle and reproduced
from the same base commit in another fresh detached worktree. Exact commands,
stdout, stderr, return codes, durations, hashes, produced files, variant
identity, and isolated SQLite paths are retained.

Run the bounded study from the repository root:

```powershell
python scripts/role_driven_validation_pass2.py `
  --repo . `
  --out runs/role-driven-validation/pass2-cross-project
```

The machine report conforms to
`schemas/role_driven_validation_pass2_report_v1.schema.json`. All experiment
artifacts remain `NOT_EVALUATED` and have no release authority.

## Interpretation rule

B beating A demonstrates value from the combined role-labelled boundary
strategy. B must also beat matched C before the improvement can be attributed
to roles. Equal B/C results mean the evidence supports boundary exploration,
not role metadata. HTTP or GUI adapter investment requires evidence from a
selected project whose real primary path uses that channel; CLI/API/file-only
results cannot justify it.
