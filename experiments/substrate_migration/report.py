"""Summarize measured evidence without promoting partial trials to qualification."""
import json
from pathlib import Path
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'artifacts/substrate-migration'


def junit(name):
    path = OUT / name
    if not path.exists():
        return {'status': 'RUNNING_OR_NOT_COMPLETED'}
    if name == 'regression.xml' and (OUT / 'final-run-start.json').exists():
        started = json.loads((OUT / 'final-run-start.json').read_text(encoding='utf-8'))['started_epoch']
        if path.stat().st_mtime < started:
            return {'status': 'RUNNING_OR_NOT_COMPLETED'}
    tree = ET.parse(path)
    cases = tree.findall('.//testcase')
    failures = [f"{c.get('classname')}::{c.get('name')}" for c in cases
                if c.find('failure') is not None or c.find('error') is not None]
    return {'tests': len(cases), 'failed': len(failures),
            'skipped': sum(c.find('skipped') is not None for c in cases),
            'failures': failures,
            'seconds': sum(float(s.get('time', 0)) for s in tree.findall('.//testsuite'))}


def write(name, text):
    (OUT / name).write_text(text.strip() + '\n', encoding='utf-8')


baseline = junit('baseline/pytest.xml')
locked = junit('locked-contracts.xml')
final = junit('regression.xml')
sdk = junit('sdk.xml')
comparison_path = OUT / 'regression-comparison.json'
comparison = (json.loads(comparison_path.read_text(encoding='utf-8'))
              if comparison_path.exists() and 'tests' in final else {})
comparison_counts = {k: len(v) if isinstance(v, (dict, list)) else v for k, v in comparison.items()}
results = {'baseline': baseline, 'locked_contracts': locked, 'regression': final, 'sdk': sdk, 'thread_isolation': junit('thread-isolation.xml')}
for name in ('sqlite-trial', 'optional-trials'):
    path = OUT / (name + '.json')
    if path.exists():
        results[name] = json.loads(path.read_text(encoding='utf-8'))
results['decisions'] = {
    'sqlite_wal': 'DEFERRED', 'official_openai_sdk': 'REJECTED',
    'httpx': 'DEFERRED', 'pydantic_ai': 'DEFERRED', 'inspect_ai': 'DEFERRED',
    'opentelemetry': 'REJECTED', 'uv_ruff': 'DEFERRED',
    'psutil_owned_process_cleanup': 'MIGRATED',
    'additional_orchestrators': 'REJECTED',
}
results['process_cleanup'] = junit('process-cleanup-confirmation.xml')
results['process_faults'] = junit('process-faults.xml')
results['process_conda_python312'] = junit('process-conda.xml')
results['new_failure_rechecks'] = [junit('new-failure-recheck.xml'), junit('new-failure-recheck-repeat.xml')]
results['qualification_gaps'] = {
    'sqlite_wal': ['real historical ledger import/hash/count reconciliation',
                   'request/response crash-window fault matrix', 'production node/attempt atomic writes',
                   'long event append/query qualification', 'Windows/WSL/Docker shared-filesystem proof'],
    'official_openai_sdk': ['Responses API and JSON Schema integration',
                           'reasoning parameters and usage/request identity integration',
                           'timeout/cancel/Gateway restart matrix', 'production route and budget integration'],
    'pydantic_ai': ['complete Worker actions/security/recovery matrix',
                    'real usage/UNKNOWN budget integration', 'demonstrable removal of existing loop'],
    'inspect_ai': ['full existing evidence/business-oracle integration',
                  'complete failure/recovery matrix', 'removal of existing evaluation runner'],
    'opentelemetry': ['exporter privacy/failure behavior', 'durable evidence replacement'],
    'uv_ruff': ['Windows launcher-PID acceptance remains failing',
                'actual Python 3.11 execution', 'Linux/Docker execution'],
    'psutil_owned_process_cleanup': ['POSIX execution environment unavailable',
                                     'detached/adversarial descendants outside the helper contract'],
}
write('qualification-results.json', json.dumps(results, indent=2))
write('baseline.md', f'''# Baseline

Source: D:/CGKN, branch codex/provider-gateway-integration-20261017,
HEAD 0bd7134ade87cb6ece13f8f7868860cd2c3ba67c. 216 porcelain status entries;
1377 current tracked/nonignored source files copied and SHA-256 checked, including
uncommitted ITER-131 changes. Original working tree was not edited. The isolated
branch is codex/substrate-migration-20261101. No remote refresh or main checkout. Cached origin/main is
1f8425dbba7c7b44d4273e25b2db20be6f8bd4f5; the local comparison is
5 remote-only / 141 HEAD-only commits, and does not represent fresh remote state.
See baseline/source-snapshot.json, git-status.txt and environment.json.

Pre-change isolated-source default full pytest (historical ignored/private
artifacts were not copied): {json.dumps(baseline)}

Command: PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q
--junitxml=artifacts/substrate-migration/baseline/pytest.xml.
Repository default profile skips marked live/slow/e2e/benchmark cases; this is
not a claim that every optional/live acceptance has executed.
Missing historical paid-plan files are ENVIRONMENT_BLOCKED, not newly broken
production functionality. baseline/failure-classification.json separates these
from observed pre-change failures. Current architecture explicitly reports ITER-131 PRODUCT_NOT_READY; that is
historical state, not a new migration regression. This baseline predates the
owned-process cleanup change.
''')
write('module-inventory.md', '''# Inventory and authority

The static-inventory.json records each Python module, LOC, imports, call sites
and provisional seed reachability classification. Dynamic imports and callable
CLI entrypoints require separate review; EXPERIMENTAL means unresolved by these
seeds, not proof of unreachability. No deletion is authorized by this inventory. External API Lab source at
D:/cgkn-provider-api-lab was inspected read-only: DomesticGateway imports its
ProviderConfigStore, ProviderComparisonService and GatewayApplication/Server.
ProviderConfigStore uses JSON under the Windows application-data directory; no
SQLite dependency was found in that package. External source/config was not edited.

| Boundary | Authority and observed references | Status |
|---|---|---|
| Agent/project decisions | cgkn.agent.project_loop -> composer, orchestration tree/compiler | CANONICAL |
| Execution | runtime.dag_runner -> executor registry -> BlockExecutionRequest/Result | CANONICAL |
| Worker | executors.llm -> CompletionClient.complete -> bounded actions, independent result checks | CANONICAL |
| State | state.store.FileRunStore -> run/attempt JSON, events JSONL, OS locks | CANONICAL |
| Domestic transport | application_network -> canonical_gateway_adapter -> gateway_client; domestic_gateway -> network_transport HTTPX -> bound streaming adapter | CANONICAL |
| Budget | scripts.provider_api_budget called by gateway_client; reserved/start/received/UNKNOWN states | CANONICAL |
| Legacy provider | explicit legacy_client/legacy_transport imports; domestic mode rejects legacy POST | COMPATIBILITY |
| Public delivery | conversation/provider_jobs -> validation/finalization -> local_packager -> public_delivery_gate | COMPATIBILITY, retained reviewed delivery authority |
| Knowledge | state.task_feedback.FrozenKnowledge -> src.cgnk_knowledge.retrieve/store, content-hashed frozen public packs | CANONICAL |
| Evaluation | scripts test gates and tests use independent business assertions | TEST_ONLY / compatibility support |
| Telemetry | RunTelemetry projects existing result/event state; not an ordinary trace exporter | CANONICAL projection |

HTTPX and urllib coexist at distinct upstream and Gateway/legacy boundaries.
The Gateway line reader supports cancellation and custom progress; upstream SSE
enforces limits, termination and identity conflicts. These are not interchangeable
duplicate implementations simply because they both read lines.
''')
write('candidate-matrix.md', '''# Candidate matrix

Exact installed versions/licenses/Python requirements: candidate-metadata.json.
Optional frameworks were installed in .venv-substrate; the candidate locked
toolchain was checked separately in .venv-substrate-check. The production change
uses the already installed psutil dependency. No global package changes.

| Candidate | Trial / compatibility | Decision |
|---|---|---|
| sqlite3/WAL (stdlib) | concurrent reserve, duplicate identity, rollback, restart UNKNOWN; production JSON readers and cross-environment sharing not migrated | DEFERRED |
| HTTPX 0.28.1/httpcore 1.0.9 | already canonical, pinned physical-interface transport and retries=0 | DEFERRED (already adopted, no new migration claim) |
| OpenAI SDK 2.17.0 | real localhost POST counts; 200/400/401/429/500; unterminated SSE behavior differs | REJECTED as drop-in replacement |
| Pydantic AI 2.64.0, MIT | bounded two-call file-read adapter; still needs CGKN paths/contracts/usage/UNKNOWN; Python >=3.11 | DEFERRED |
| Inspect AI 0.3.287, MIT | mock positive/negative scoring, max_retries=0; business evidence conversion remains; Python >=3.11 | DEFERRED |
| OpenTelemetry API 1.45.2, Apache-2.0 | no-op spans and no exporter; cannot replace deterministic evidence/usage projection | REJECTED |
| uv 0.13.6 / Ruff 0.17.3 | hash lock and lint work; 367 core contracts pass; full Windows trial exposes launcher-PID assumptions | DEFERRED; default CI unchanged |
| Existing psutil 7.x, BSD-3-Clause | replaces duplicate parent-only runtime termination with bounded descendant termination/wait; real unrelated-process control and fault injection | MIGRATED; full-suite limitations in regression-report.md |
| DBOS/LangGraph/LiteLLM/new harness/storage cluster | no replacement necessity shown; additional authority/dependency cost | REJECTED for this scope |

Primary references checked: [HTTPX transports](https://www.python-httpx.org/advanced/transports/),
[Pydantic retry layers](https://pydantic.dev/docs/ai/core-concepts/retries/),
[Inspect concurrency/retries](https://inspect.aisi.org.uk/models-concurrency.html),
[uv locks](https://docs.astral.sh/uv/pip/compile/),
[psutil process identity and termination](https://psutil.readthedocs.io/stable/).
Dependency counts in metadata include optional-extra declarations, not just
installed runtime requirements. candidate-versions.json lists the actually
installed experiment environment. Package metadata is not a vulnerability audit
or proof of future maintenance.
''')
write('migration-decisions.md', '''# Decisions

The owned-process cleanup boundary in scripts/customer_runtime_runner.py now uses
the existing psutil dependency. Parent-only termination was insufficient for the
Windows virtual-environment launcher: its descendant retained the runtime working
directory during cleanup. The same default runtime now terminates/waits for the
observed owned descendants; the two duplicate termination sequences are removed.
An unrelated sibling remains alive in the real-process negative control. Forced
termination, surviving descendants and already-reaped PID guards are tested.
This is a bounded reliability improvement, not a new runtime or sandbox.
Preserve the current single planner, DAG, FileRunStore and reviewed delivery route.

SQLite's transaction prototype passes, but a full immutable historical ledger
import and read-path migration, crash matrix and Windows/WSL/Docker sharing proof
are missing. Nine production modules directly mention run/attempt/event paths,
including provenance, acceptance and trusted_samples. A database hidden behind
FileRunStore alone would retain those filesystem contracts rather than remove
them. Do not risk UNKNOWN history for a prototype result.

The official SDK cannot directly replace strict SSE handling: the same incomplete
event raises CGKN stream_unterminated_event while its decoder returns no events.
The existing HTTPX transport is already a mature library; replacing it adds no
demonstrated reduction and risks bound-network policy.

Pydantic AI and Inspect work on fixed offline examples but would require new
adapters while retaining core contracts and evidence. No old loop/evaluation
implementation can yet be removed. OTel similarly would add a second projection.
These outcomes explicitly do not satisfy full migration qualification.

The candidate toolchain lock passed all 367 core contracts. The full Windows
trial still exposes a Gateway test that equates launcher PID with worker PID.
Its assertion remains intact. Default CI was restored to the original content;
the lock remains an explicitly deferred experiment. Pillow was added after a
concrete missing-import failure, matching the host's existing version.

Commits are blocked: the canonical publisher has no local-only commit operation,
and its publish function necessarily pushes. The task forbids remote pushes.
No direct git add/commit bypass, forged TestReceipt, or publisher-runner interception
was used. The worktree also contains the copied uncommitted source baseline.
''')
write('provider-cost-ledger.md', '''# Provider cost

Task-initiated paid Provider POSTs: 0. Task-initiated model cost: RMB 0.00.
No real paid-call budget reservation or historical ledger mutation was performed.
Offline tests do exercise temporary mock budget ledgers. No live smoke
was necessary for the bounded changes. Existing Gateway process and route remain
untouched. SDK trials use loopback mock POSTs; Pydantic/Inspect use local models.
This is not a claim of real Qwen/DeepSeek success or a reconciliation of other
concurrently running processes. User cap remains <=2 POSTs / RMB 0.20, unused.
''')
write('regression-report.md', f'''# Regression evidence

Baseline: {json.dumps(baseline)}

Clean locked environment contracts: {json.dumps(locked)}

Final default full regression: {json.dumps(final)}

Case identity comparison against the baseline: {json.dumps(comparison_counts)}
See regression-comparison.json for exact case IDs. Baseline failures and missing
historical evidence do not become PASS merely because the migration is bounded.

Final pytest terminal summary: 3355 passed, 48 failed, 14 errors, 350 skipped,
26 subtests passed, 1784.61 seconds. Baseline: 3349 passed, 51 failed, 14 errors,
350 skipped, 24 subtests passed, 2045.36 seconds. JUnit identities include subtest
records, so their counts differ from pytest terminal totals. The duration change
is not a controlled performance result: outcomes and machine load differ.

The one newly failing case was the isolated real-Mihomo watchdog crash recovery
test's five-second stop wait. Two unchanged standalone reruns passed (20.01 and
19.91 seconds total test duration). Its test uses temporary config, loopback
listeners and tun=false. This is an observed intermittent failure, with root
cause unresolved; the original full-run failure is retained and is not relabeled
PASS. Neither network_watchdog.py nor this test was modified. See
new-failure-recheck.xml and new-failure-recheck-repeat.xml.

SDK candidate: {json.dumps(sdk)}

Thread-isolation targeted verification: {json.dumps(junit("thread-isolation.xml"))}

The initial locked full suite is retained as locked-full-initial.xml/log. It
exposed the process cleanup fault and missing Pillow. The final regression uses
the original host interpreter after the production cleanup and Thread isolation
changes. Additional process-fault checks are in process-faults.xml.

See XML/logs for assertions. Optional trials and SQLite prototype are scoped
experiments, not full fault-matrix qualification. Product direction gate is
recorded in direction-gate.json. Docker daemon is ENVIRONMENT_BLOCKED. No
live-provider, physical network egress or cross-OS shared-WAL PASS is claimed.
''')
delta = json.loads((OUT / 'production-delta.json').read_text(encoding='utf-8'))
write('complexity-before-after.md', f'''# Complexity

Production lines removed: {delta['removed_lines']}; added: {delta['added_lines']};
net change: +{delta['after_lines'] - delta['before_lines']} lines. Two duplicated
parent-only termination sequences now call one private psutil-backed helper.
Existing test assertions removed or weakened: 0. New runtime dependency packages: 0
(psutil was already in requirements-network.txt; host version 7.0.0).
Production authority/path count change: 0. No second planner/scheduler/state store.
Source inventory baseline: 661 Python modules, 187933 lines, 5198 distinct-import
entries under the initial inventory method, 87749 call sites. The refined import
inventory also includes imported symbol candidates, so its edge count is not
directly comparable with the initial method.

Added maintenance: offline experiment scripts and a locked host-tools environment.
The optional frameworks remain isolated experiment dependencies, not core imports.
No net production code reduction or general runtime speedup is demonstrated.
Three identical-content runtime comparisons show old cleanup FAIL/new PASS at
roughly the same sub-second scale; exact repeated samples are in
process-differential.json. This is a correctness repair, not a speed benchmark.
SQLite trial timing is a prototype runtime, not a production speedup.
''')
write('remaining-risks.md', '''# Remaining risks and incomplete acceptance

- Full candidate fault/security/recovery matrices are not complete; minimal passes
  must not be promoted into migration success.
- Static module classification is provisional for dynamic/plugin entrypoints;
  no UNREACHABLE classification or deletion is asserted without proof.
- Production ledger migration, versioned schemas and historical hash/count checks
  remain unimplemented; original ledgers remain untouched.
- Docker daemon is unavailable; WSL startup fails with ERROR_FILE_NOT_FOUND.
- Python 3.11 lock resolution does not constitute an executed interpreter test.
- psutil cleanup covers observed descendants of a live owned runtime, not an OS
  sandbox or a guarantee against adversarial detach/spawn races. POSIX execution
  is environment-blocked; Popen retains ownership of parent reaping by design.
- The candidate Windows venv toolchain is not the default CI path. Its Gateway
  launcher-PID assertion remains an unresolved qualification condition.
- No live smoke and no public delivery readiness claim; ITER-131 remains not ready.
- Local commits cannot use the existing authority without also pushing; no commits
  made. Source snapshot and isolated worktree preserve review/rollback material.
- The user's overall production-code reduction goal has not been achieved.
- Final full regression has one new intermittent watchdog stop timeout; two
  targeted reruns pass, but its cause remains unresolved. Overall suite is not green.
''')
acceptance = {
    'DAG and restart': 'tests.runtime.test_dag_runner::test_real_vertical_slice_and_resume',
    'Affected-only retry': 'tests.runtime.test_dag_runner::test_affected_subgraph_rerun_reuses_unaffected_successes',
    'UNKNOWN no replay': 'tests.runtime.test_event_frontier::test_unknown_dispatch_is_not_replayed',
    'Cancellation': 'tests.runtime.test_event_frontier::test_inflight_cancel_preserves_observed_result_without_success',
    'Parallel dependencies': 'tests.runtime.test_parallel_processes::test_process_overlap_join_and_durable_resume',
    'Worker file modification': 'tests.executors.test_llm_executor::test_worker_actions_read_list_write_patch_and_usage',
    'Independent business acceptance': 'tests.runtime.test_execution_continuity::test_real_sqlite_process_acceptance_positive_negative',
    'Illegal output rejected': 'tests.runtime.test_artifact_runtime_contract::test_provider_invalid_output_creates_diagnostic_and_no_artifact',
    'Budget exhausted before next POST': 'tests.test_provider_api_budget::test_budget_is_checked_before_second_transport',
    'Parallel simulated providers': 'tests.providers.test_streaming_http.TestHTTP::test_parallel_provider_streams_do_not_block_one_another',
    'Frozen knowledge reuse and isolation': 'tests.runtime.test_knowledge_feedback_qualification::test_candidate_not_promoted_same_run_and_contradictions_downgrade',
    'Failure evidence and repair': 'tests.execution.test_observation_contract::test_real_process_to_typed_feedback_fake_repair_checker_statistics_audit',
}
case_status = {}
if 'tests' in final:
    for case in ET.parse(OUT / 'regression.xml').findall('.//testcase'):
        key = f"{case.get('classname')}::{case.get('name')}"
        case_status[key] = ('FAIL' if case.find('failure') is not None or case.find('error') is not None
                            else 'SKIP' if case.find('skipped') is not None else 'PASS')
write('acceptance-map.json', json.dumps({'core_witnesses': {label: {'test': key,
    'status': case_status.get(key, 'NOT_VERIFIED_IN_COMPLETED_FINAL_RUN')} for label, key in acceptance.items()},
    'evidence': 'regression.xml', 'scope': 'offline real filesystem/process/DAG; model decisions are fixed fixtures, no paid models'}, indent=2))
write('final-report.md', f'''# Substrate migration result

Status: LIMITED CHANGE — owned-process cleanup uses the existing psutil library;
the broader net code-reduction goal is not achieved. No architecture-slimming
success or general product readiness is claimed.

Final full regression: **3355 passed / 48 failed / 14 errors / 350 skipped**.
Compared with baseline, 61 failing cases recur, four stop failing, and one
watchdog stop-timeout appears. That case passes two unchanged targeted reruns;
its root cause remains unresolved. Zero missing tests, zero newly skipped tests,
five added tests. The twelve offline acceptance witnesses in acceptance-map.json
all pass. Product direction gate, changed-file compile and targeted Ruff pass.
Original source snapshot verification: 1377 files checked, zero differences.

Implemented and executed isolated SQLite, SDK, Pydantic AI, Inspect AI and OTel
trials. Added a candidate hash-locked tool environment and targeted Ruff checks;
default CI remains unchanged because full Windows toolchain qualification failed.
See qualification-results.json and regression-report.md for actual
counts and limits. The conversation tests now replace only bridge.threading, preserving real
Windows subprocess pipe-reader threads; all 20 original assertions/tests pass.
Customer runtime cleanup now waits for owned descendants, keeps parent reaping
with Popen, and fails closed when cleanup cannot complete. Existing duplicate
termination code was removed, but production LOC increased (production-delta.json).
No new dependency package, planner, scheduler or state authority was added.

Core contracts, bounded Worker actions, independent verification, knowledge,
budget/UNKNOWN and delivery ownership remain in the original implementation.
Reasons for not adopting frameworks: incomplete migration proof, incompatible
stream semantics, unchanged adapter responsibility, Python-version constraints,
or no removable existing implementation. API spend RMB 0.00, no remote push.

Git HEAD remains the copied baseline commit; no local commit was possible through
the mandatory publisher without its automatic remote push. Review the dedicated
worktree and source snapshot; never overwrite original uncommitted work.

## Answers to the ten acceptance questions

1. Replaced two parent-only cleanup sequences with one owned-process helper using
   existing psutil. Kept HTTPX, FileRunStore and the bounded executor contracts.
2. Removed {delta['removed_lines']} production lines and added {delta['added_lines']};
   net +{delta['after_lines'] - delta['before_lines']}. No broad dead-code deletion.
3. Added zero runtime packages. Optional candidate frameworks and uv/Ruff are
   isolated experiment dependencies; exact versions are recorded separately.
4. Consolidated two cleanup call sites. Removed zero public execution routes or
   state authorities; no unreachability evidence justified their removal.
5. Centralized cleanup and repaired the measured Windows failure. Overall
   maintenance complexity reduction is not proven; experiment tooling adds cost.
6. Three before/after fixtures consistently changed cleanup FAIL to PASS.
   No repeatable general performance improvement is claimed.
7. Existing assertions are retained. Completed full-run case comparison:
   {json.dumps(comparison_counts)}. See acceptance-map.json for individual witness
   results; the full suite still has baseline failures and optional skipped tests.
8. Paid POSTs 0; cost RMB 0.00; no paid reservation, price estimate or live success
   is implied by local mocks.
9. SDK SSE behavior differs; Pydantic/Inspect retain adapter responsibilities;
   SQLite lacks historical migration/cross-OS proof; OTel adds a projection;
   uv default adoption is deferred by unresolved Windows launcher-PID assumptions.
10. CGKN should retain Agent decisions, capability contracts, tree/DAG composition,
    bounded execution policy, independent acceptance/evidence binding, budget and
    UNKNOWN policy, knowledge policy, and the reviewed public delivery decision.
''')
