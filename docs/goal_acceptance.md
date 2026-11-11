# Goal evidence on the existing project loop

`AgentProjectLoop` accepts an optional `GoalAcceptance` bound to its
`FileRunStore`. The controller supplies frozen public requirements and a
checker-to-executor registry. The Agent proposes project-specific phases and
goals through `ActionComposer`'s `plan` operation. It still uses the original
CapabilityTree, compiler, DAGRunner and bounded executors.

A goal identifies `id`, `phase_id`, `requirement_refs`, `acceptance`,
`subject_refs`, `checker`, and optional existing `task_refs`. Registered checker
names and current subject identity keys appear in decision context. Unknown
names are rejected with the available registry keys, without rewriting the
Agent's proposal. Required coverage cannot disappear during re-planning.

The registered checker emits `goal_check` containing the goal identity,
condition hash, subject identities, valid execution indicator, observed
verdict and raw evidence references. Acceptance consumes the actual stored
Block receipt from this run. Producer claims, successful execution alone,
missing checks and stale identities do not verify goals. Old evidence remains
in the append-only plan/check histories within `goal_acceptance.json`.

`continuous=True` turns `max_decisions` into a checkpoint interval. Ordinary
limited loops retain their previous behavior. The checkpoint retains the
tree, recent raw results, failures and repeated-attempt state. Interrupted
dispatches become `INTERRUPTED_UNKNOWN`; recovery does not replay them.

The scoped Provider policy `accounting_only` requires an explicit user
authorization reference on each reservation. It keeps reservations and usage
settlement, and records exceeded historical limits, without applying them as
admission gates. Other calls remain limited. Request deadlines, finite network
retries and bounded concurrency remain active.

Render an existing run without changing its evidence:

```powershell
python scripts/render_goal_progress.py --run-dir F:/CGKN-ITER-113/dev-stage-13/run/cgkn-state/product-eval076/dev113-cgnk-stage-10 --output F:/CGKN-ITER-115/stage-view.html
```

The experimental real route's isolated Observer provides **proxy** engineering
evidence. It cannot substitute for external acceptance, independent mutation
tests, or required human domain review. Its disposable files never merge into
the candidate. Execution batch numbers remain distinct from Agent milestones.

Offline fixture code under `tests/fixtures/goal_domains.py` is host-authored
mechanism testing, not an autonomously generated product or a real social
platform integration.

## Independent acceptance and metric projections (ACV4)

The original requirement dictionary is frozen per run, including necessity,
weights, sources, versions and any AND/OR children. Goal proposals cannot weaken
an existing mapping or condition. Child edges express requirement composition;
only the existing execution DAG expresses runtime dependencies. An OR alternative
is not independently mandatory unless the original contract says so. Allocate
weights in the original dictionary (for example parent 0, alternatives .5/.5);
adding checker goals never adds denominator weight. Empty or zero-weight
requirements cannot establish completion.

`GoalAcceptance` remains the current acceptance authority. It derives hard
verdict, completion and evidence coverage from its stored receipts. Valid
same-node newer attempts supersede earlier applicable attempts; independent
rechecks name `supersedes_receipts` explicitly. Invalid observations cannot
supersede counterexamples. History is retained. Unresolved independent failures
win over passes regardless of notification order. Checker bindings are frozen;
changing their contract requires an explicitly versioned run. Historical audit
gaps are not rewritten into current business failures.

`cgkn.executors.measurement.FileMeasurementExecutor` implements `measure.file@1`
through the common Block boundary and can be registered in `ExecutorRegistry`.
The trusted host supplies a bounded file root and immutable contract dictionary;
the executor receives only `contract_id`. Contracts specify goal, version,
artifact SHA256, subject, JSON field and predicate. Supported predicates are
strict equality, set equality and numeric tolerance. A business mismatch yields
successful execution plus FAILED verdict; parse/IO errors yield failed execution.
These are host-authored checker calibration fixtures, not generated products.
The host must isolate trusted contracts/private samples from candidate writers;
this class alone is not a process sandbox or a general GUI/semantic checker.

`python -m scripts.task_metrics {effectiveness,cost,time} --input INPUT.json
--output NEW.json` writes a new read-only projection. Input is an explicitly
trusted evidence export, not a declaration that arbitrary input references have
been verified. The module does not fetch Provider evidence or alter routes,
assigned tasks, acceptance records or published knowledge. Output paths must be
new. `requirements-metrics.txt` supplies the optional SciPy Beta quantile dependency.

Effectiveness input contains samples, a fixed task_ids cohort, actual model and
version, task family/difficulty, tool/context/repair protocol, and positive time
and cost references. Each sample keeps D (delivery) separate from Y (business),
revision history and complete time/cost. Missing or unconfirmed records remain
pending; all terms use one settled subset and are PROVISIONAL if any task is
pending. An empty subset is NOT_COMPUTABLE. The separate business view is
conditional on applicable attributed business judgments. No value is a routing
instruction, business acceptance threshold, or calibrated universal reliability.

Cost receipts distinguish actual and estimated charges and preserve amounts on
unknown requests. Duplicate request notifications are idempotent; actual retries
have distinct identities. `worker_calls` is a compatible count of bounded worker
executions, not upstream HTTP attempts. `request_counts` separately reports
application requests, purpose/schema, configured role and logical task count.

ACV4 independent commands, frozen inputs, failures and final receipts reside in
`F:/CGKN-ACV4-20261030-01`. Joint generation/evaluation/routing/parallel experiments
are deferred by scope, not removed from valid existing functionality.

## V5 provenance and production samples

Production runs freeze `provenance_contract.json` in the existing FileRunStore.
`EvidenceBoundExecutor` wraps a bounded checker and snapshots candidate bytes,
checker source/version and raw observations. `ProvenanceGate` verifies the
requirement, candidate, checker, observation and actual execution receipt chain
before GoalAcceptance can accept it. Invalid evidence cannot replace a valid
counterexample; missing legacy provenance remains explicitly unverified.
Explicit hash-bound imports support a versioned checker correction without
rewriting the old run. The coordinator and its local store are the trust root;
hashes do not defend against a privileged host rewriting all authorities.

`python -m scripts.task_metrics trusted --store STORE --project PROJECT --run RUN
--input REFS.json --output NEW.json` reconstructs a read-only projection from
immutable metric revisions. Provider requests, responses, model identity, worker
outputs, artifact hashes, full time intervals and usage-based costs are checked.
Unsettled costs remain unknown. The pure `effectiveness` command is explicitly
an unverified input projection. Neither entry changes routing or promotes knowledge.

An evaluator-correction continuation is a provisional observation, not a clean
sample of the originally frozen repair protocol. All calls and elapsed time
remain charged; corrected first-pass acceptance is distinct from an error-free
evaluation process. One task with multiple revisions remains one sample.
V5 evidence is in `F:/CGKN-ACV5-20261030-01`. The single real Qwen task and bounded
repair establish neither stable model rankings nor general product readiness.
