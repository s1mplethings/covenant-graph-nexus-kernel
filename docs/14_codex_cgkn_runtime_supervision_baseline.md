# Codex–CGKN Runtime Supervision Baseline

CGKN is the long-running project-production system. The active Codex task is
its only user-facing conversation interface. Codex may start, attach to, and
supervise declared CGKN checkpoints, but the conversation itself is owned by
the Codex app rather than a repository listener.

## Ownership

- The Codex app owns user messages, attachments, visible progress, review
  decisions, and artifact rendering.
- CGKN owns durable project state, `whiteboard`, `agent_session`, requirements,
  generation orchestration, and recovery state.
- The Provider route is the only generated-candidate author.
- Canonical inspectors own evidence evaluation.
- `local_packager` is the only delivery exit.
- The public delivery gate controls whether an artifact may be exposed.

The repository must not start a second conversation service, poll an external
messaging API, require a conversation credential, or introduce another UI
transport. `scripts/codex_conversation.py` is import-only and is called from
the active Codex task.

## Persistent False-Pass supervision

Checkpoint supervision resumes one identity-bound Codex thread. A checkpoint
binds its sequence, previous hash, repository identity, conversation, project,
run, bounded context references, requested action, and fixed authority fields.
Supervisor results are support state and never formal evidence.

The persistent thread is an adversarial auditor, not a project worker. It is
called only when CGKN proposes a positive transition at requirements freeze,
integration complete, or pre-public-delivery. It treats CGKN PASS/READY claims
as untrusted, checks the underlying source, tests, runtime observations,
candidate identity, requirement coverage, and dependencies, and must bind any
challenge to concrete evidence. Ordinary leaf completion, Provider failure,
test failure, and API retry bypass Codex deterministically.

Canonical outcomes are `resume`, `rework_project`, `recheck_evidence`,
`repair_kernel`, `user_decision`, or `halt`. The deterministic router sends
project defects to Provider repair, evidence defects to canonical rechecking,
and kernel defects to a separate allowlisted Codex repair mirror. The supervisor cannot
impersonate the Provider, edit a sealed candidate, assert formal evidence,
package, or deliver.

## Customer flow

```text
Codex user message or attachment
-> CGKN intake and shared state
-> Provider API planning and parallel ProviderJob execution
-> deterministic ownership check, merge, and integration
-> Provider validation and canonical evidence
-> sparse positive-transition False-Pass audit
-> deterministic route consumption (`rework_project`, `recheck_evidence`, or governed `repair_kernel`)
-> original positive checkpoint re-emission and bounded re-audit
-> canonical evidence
-> Codex user review when required
-> local_packager and delivery gate
-> local artifact links rendered in the same Codex task
```

Failures remain bound to project/run state and can be diagnosed or resumed in
the same task. A request-scoped Codex specialist call is allowed only as a
bounded advisory adapter; it is not a second conversation, generation, or
delivery path.

The read-only audit turn never becomes writable. A `repair_kernel` result
creates a governed request requiring reproduction, a regression test, an
allowlisted isolated workspace-write execution, passing checks, and re-audit of
the original checkpoint. Generated candidates, artifacts, runs, workspaces,
packages, and delivery state are absent from that writable mirror.

Production route consumption is bounded by
`MAX_SUPERVISION_REWORK_ROUNDS=2`. Two consecutive refusals at the same
positive transition stop as `NEEDS_REWORK`; `user_decision` waits for review
and `halt` stops explicitly. Project repair resumes the existing split-file
Provider leaf executor, evidence recheck calls no Provider, and no pending
route receipt can act as evidence or delivery authority.
