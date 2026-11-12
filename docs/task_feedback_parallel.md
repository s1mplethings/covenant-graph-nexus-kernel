# ITER-116 feedback, models and concurrency

The existing DAGRunner coordinates ready nodes as completion events arrive. It
commits receipts and derives task feedback before the next Agent checkpoint.
Execution success is not goal acceptance. TaskFeedback statistics use current
GoalAcceptance evidence with explicit task-receipt linkage; unlinked work remains
unassessed. An old success cannot supersede a newer failed goal check.

Task evaluation is advisory. `task.evaluate@1` consumes a public attempt receipt,
records a versioned evaluation, and creates an uncertain knowledge candidate via
the existing ProjectKnowledgePack interface. Candidates are not automatically
approved. FrozenKnowledge retrieves only relevant public, accepted, active items
from an explicitly supplied immutable pack. No private Corpus is searched.

Concrete model IDs use `ModelRoleConfig.model_id`; `model` remains the reviewed
Provider alias for Gateway routing. Authenticated inventory is required before
accepting an override. Request and returned model identities are both recorded;
an identity mismatch cannot contribute verified model-success statistics.

## Lifecycle

The coordinator has an OS-backed run lock. Receipts persist before run-state
updates. Recovery reuses committed receipts; interrupted work without a receipt
is BLOCKED with unknown outcome, never automatically replayed. Explicit retries
preserve prior attempts and invalidate the affected downstream graph.

Cancellation before dispatch creates blocked receipts without side effects.
In-flight cancellation invokes an executor cancel method when available and
retains late outputs and usage as blocked observations. It does not claim remote
termination. Executors without cancellation must return within their own bounded
request/tool timeout. Arbitrary unbounded Python executors are not forcibly
terminated by ThreadPoolExecutor. Existing isolated tool process-group cleanup
and NET finite request timeout/retry policy remain the execution boundary.

Evaluation resolves the exact immutable attempt identity, including old attempts
after a retry and tasks outside the bounded planner context. Receipt identity and
hash are checked before any evaluator call. Late evaluations remain attached to
their original attempt and do not replace the current attempt's contribution.

Evaluation request intent persists before submission. An unresolved intent does
not trigger a blind paid retry; inspect the raw response/intent before recovery.
This version has no automatic reconciliation of malformed evaluation responses.
If a complete evaluator response was durably saved before evaluation commit
failed, the same revision can recover it without a Provider call. Recovery checks
the original target, revision, public prompt and JSON schema again, then commits
the advisory record. Cached recovery does not count the original token usage a
second time. Missing or invalid responses remain blocked/failed, never replayed.

Trusted executor workspace claims govern serialization. Independent workspaces
can overlap (maximum two workers); conflicting writes serialize. Graph changes
occur through the existing graph commit/checkpoint mechanism, not a second DAG.

## Evidence limits

Controlled Providers and fixture executors prove framework behavior only. Docker
conformance proves permitted operations, persistence and audited container
execution, not business delivery. Real model concurrency and independent product
acceptance require a successful real-task run and are reported separately.
