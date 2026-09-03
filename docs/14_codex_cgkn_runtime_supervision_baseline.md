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

## Persistent supervision

Checkpoint supervision resumes one identity-bound Codex thread. A checkpoint
binds its sequence, previous hash, repository identity, conversation, project,
run, bounded context references, requested action, and fixed authority fields.
Supervisor results are support state and never formal evidence.

Allowed outcomes are bounded observation, advice, a governed `repair_cgkn`
request, a user decision request, resume, or halt. The supervisor cannot
impersonate the Provider, edit a sealed candidate, assert formal evidence,
package, or deliver.

## Customer flow

```text
Codex user message or attachment
-> CGKN intake and shared state
-> requirements/design confirmation when needed
-> Provider generation and validation
-> canonical evidence
-> Codex user review when required
-> local_packager and delivery gate
-> local artifact links rendered in the same Codex task
```

Failures remain bound to project/run state and can be diagnosed or resumed in
the same task. A request-scoped Codex specialist call is allowed only as a
bounded advisory adapter; it is not a second conversation, generation, or
delivery path.
