# Codex–CGKN Runtime Supervision Baseline

Status: **normative architecture baseline**

This document fixes the intended runtime relationship among Codex, CGKN, and
Telegram. It is a design authority for future implementation and review. It
does not claim that every runtime component described here is already
implemented or formally evaluated.

中文基准摘要：CGKN 是独立常驻运行的主体，Telegram Bot 与 Mini App 是
CGKN 内部的用户交流入口；Codex 负责启动或接管 CGKN，并通过同一条可恢复的
监督会话在关键检查点检查、诊断和执行受控修复。每条 Telegram 消息临时启动
一个全新 Codex 进程不是目标架构。Codex 不得取代 Provider 写入封存候选项目，
也不得自行授予正式证据、打包或公开交付权限。

## 1. Foundational invariant

CGKN is the independently running project-production system. Telegram is an
interaction channel owned by and contained within CGKN. Codex is the operator
and bounded runtime supervisor that starts or attaches to CGKN, observes
declared checkpoints, diagnoses problems, and performs permitted repairs.

The required ownership direction is:

```text
Codex operator / persistent supervisor
                 |
                 | starts, attaches, observes, diagnoses, repairs
                 v
        long-running CGKN service
        |        |             |
        |        |             +-> reviewed Provider generation route
        |        +-> project state, whiteboard, agent_session, evidence
        +-> Telegram Bot and optional Telegram Mini App
                 ^
                 |
                 v
                user
```

The following inversion is prohibited as the target architecture:

```text
Telegram -> start a fresh one-shot Codex process -> treat Codex as CGKN
```

A request-scoped Codex call may remain only as a transitional adapter or a
bounded specialist invocation. It is not the durable runtime supervisor and
must not become a second Telegram, generation, packaging, or delivery
mainline.

CGKN exposes two mutually exclusive public runtime profiles around that one
formal mainline:

- `API-only` starts the Telegram bridge directly, disables runtime supervision
  and every Codex design invocation, and uses its own session, log, upload,
  memory, and Provider-candidate roots.
- `CGKN Codex Edition` starts the persistent supervisor host, which starts the
  bridge with a separate runtime-data profile and forces the historical
  one-shot Codex design CLI off. All Codex activity belongs to the one stored,
  resumable supervisor thread.

Selecting a profile changes operational supervision and support-state
ownership only. It never selects a different Provider author, evidence
authority, packager, public gate, or delivery route.

## 2. Runtime roles

### 2.1 CGKN

CGKN owns the long-running operational loop. It:

- receives and normalizes Telegram Bot and Mini App input;
- persists chat, project, whiteboard, workflow, and `agent_session` state;
- freezes requirements, design decisions, interfaces, and acceptance checks;
- runs the reviewed Provider generation route;
- coordinates independent feature leaves and integration;
- requests and records applicable test, runtime, visual, and review evidence;
- invokes `local_packager` and the public delivery gate through the existing
  route only;
- reports user-safe progress and decisions through Telegram.

Ordinary CGKN work must not require a new Codex process for every Telegram
message. If the supervisor is temporarily unavailable, CGKN may continue only
work that does not cross a checkpoint requiring supervision or new authority.

### 2.2 Telegram

Telegram is a CGKN-owned customer interface, not a Codex transport and not a
generation engine. Telegram messages first enter CGKN intake and the shared
project state. Telegram never bypasses CGKN to issue unbounded shell, code,
Provider, packaging, or delivery instructions to Codex.

The Bot is the default conversational interface. A Mini App is an optional
CGKN interface for visual or repeated interactions. Both surfaces use the same
project identity, action contracts, whiteboard, and guarded generation route.

### 2.3 Codex

Codex owns startup/attachment and bounded supervision. It:

- starts CGKN or attaches to an already healthy CGKN service;
- verifies configuration, process identity, health, and checkpoint continuity;
- resumes one persistent supervision thread rather than creating an unrelated
  thread for each customer message;
- consumes bounded, secret-redacted, identity-bound checkpoint context;
- diagnoses runtime, planning, integration, and test failures;
- may repair CGKN source, configuration, and tests within the repair policy
  below;
- records advice, repair receipts, test results, and resume decisions in
  shared support state;
- stops, waits, or requests a user decision when authority or evidence is
  insufficient.

Keeping the Codex desktop window open is an operator convenience, not the
runtime protocol. The durable protocol must use an approved programmatic
adapter that can start, continue, and resume a persistent Codex thread and can
recover its stored thread identity after process restart.

## 3. Startup and attachment lifecycle

The baseline startup sequence is:

1. Codex runs CGKN doctor/status checks without exposing secrets.
2. Codex starts the CGKN supervisor host or attaches to its recorded process.
3. The host starts or verifies the long-running CGKN service and Telegram
   intake.
4. The supervisor records process identity, health state, checkpoint cursor,
   persistent Codex thread identity, and configuration identity under
   project-local support state.
5. CGKN announces readiness through Telegram only after intake and state
   persistence are healthy.
6. Codex remains available for declared checkpoint events; it does not pollute
   normal customer dialogue with internal supervision narration.

Starting the desktop app alone is not evidence that CGKN or the supervisor is
running. Readiness requires an observed process plus a successful health and
state-continuity check.

## 4. Persistent supervision session

The supervisor must persist at least:

- `supervisor_instance_id`;
- Codex `thread_id` or equivalent resumable conversation identity;
- CGKN process identity and start time;
- repository/worktree identity;
- last consumed checkpoint sequence and hash;
- current supervision workflow state;
- last successful health timestamp;
- bounded restart count and last failure category.

These are support and workflow fields, not formal evidence. The thread identity
must never contain a credential. A stale thread, changed repository identity,
or checkpoint hash mismatch requires explicit recovery; it must not be silently
treated as continuous supervision.

## 5. Mandatory checkpoint model

CGKN emits an identity-bound checkpoint event when any of the following occurs:

| Checkpoint | Default Codex action | Continue rule |
| --- | --- | --- |
| service startup or reattachment | verify health, configuration, state identity | health and continuity checks succeed |
| requirements frozen | inspect ambiguity, scope, input/output, side effects | frozen contract is coherent or user resolves it |
| interface/design frozen | inspect interaction surfaces and visual acceptance | required design confirmation exists |
| before Provider generation | verify reviewed route, sealed planning context, quota policy | existing generation gate permits start |
| Provider output received | inspect validation and causal trace failures | Provider output validation succeeds |
| feature integration complete | inspect interface drift and ownership conflicts | integration checks succeed |
| test/runtime/visual failure | diagnose, perform permitted repair, rerun affected checks | applicable checks pass or remain honestly blocked |
| before packaging | verify canonical evidence and review requirements | `local_packager` prerequisites succeed |
| before public delivery | inspect delivery gate inputs only | public delivery gate authorizes the attempt |
| CGKN crash or repeated degraded health | diagnose, apply bounded recovery, or halt | restart budget and recovery checks succeed |

Each checkpoint event must bind a checkpoint id and sequence, chat/project/run
identity when applicable, type, reason, severity, context references and
hashes, requested action, requested authority, and current workflow state.
Free-form logs alone are not a checkpoint contract.

## 6. Codex action and repair policy

Allowed supervisor outcomes are:

- `observe`: record that no intervention is required;
- `advise`: return a bounded validated brief to CGKN support state;
- `repair_cgkn`: change CGKN-owned code, configuration, documentation, or
  tests for the diagnosed defect, then run proportionate regression;
- `request_user_decision`: ask through CGKN/Telegram when business scope,
  irreversible action, cost, credentials, or external publication is involved;
- `resume`: release the exact blocked checkpoint after its requirements pass;
- `halt`: keep the checkpoint blocked with an explicit diagnosis.

An automatic `repair_cgkn` must be bounded to the diagnosed failure, preserve
unrelated user changes, retain an auditable diff, update kernel documentation
and guards when kernel files change, and pass the declared checks before a
restart or resume. Repeated repair/restart failure must halt instead of looping
indefinitely.

Codex supervision must never:

- impersonate the reviewed Provider or author a sealed generated candidate;
- convert advice, file existence, workflow completion, or a passing local test
  into formal evidence authority;
- approve its own public delivery;
- bypass Provider output validation, post-build finalization, canonical
  evidence, user review, `local_packager`, `public_delivery_gate`, the delivery
  receipt, or the canonical final verdict;
- expose secrets or internal control jargon in customer replies;
- create a second Telegram generation or delivery route.

## 7. Telegram customer flow

The customer-visible flow remains simple:

```text
user message in Telegram
-> CGKN intake and project memory
-> requirement/design conversation when needed
-> explicit confirmation when required
-> reviewed Provider generation
-> tests and evidence
-> review, packaging, delivery
-> Telegram result
```

Codex intervention is normally invisible except when CGKN needs a user
decision or reports that supervision has safely paused a checkpoint. The user
does not need to issue a special “call Codex” command.

## 8. Failure and recovery behavior

- If Telegram is unavailable, CGKN retains state and resumes intake from the
  recorded update cursor; it does not start a replacement generation route.
- If CGKN exits, the supervisor diagnoses the exit before a bounded restart.
- If Codex supervision is unavailable, CGKN marks the affected checkpoint as
  waiting or blocked and continues only unrelated safe work.
- If persistent thread recovery fails, the supervisor prepares a new bounded
  handoff from durable CGKN state and records the discontinuity; it does not
  pretend that a new thread is the previous one.
- If Provider, test, evidence, packaging, or delivery fails, the canonical
  failure remains authoritative. Supervisor advice cannot overwrite it.

## 9. Formal generation and delivery route

This baseline changes operational supervision, not formal authorship or
delivery authority. Telegram default generation remains:

```text
customer request
-> API/provider project generation
-> provider output validation
-> post-build finalization
-> canonical test/runtime/visual evidence
-> user review when required
-> local_packager
-> public_delivery_gate
-> delivery receipt
-> bind active project
-> canonical final verdict
```

Whiteboard and `agent_session` remain the shared communication state.
`local_packager` remains the only delivery exit.

## 10. Implementation conformance

An implementation conforms to this baseline only when tests or runtime
evidence demonstrate all of the following:

1. Codex can start or attach to CGKN and observe a stable health identity.
2. CGKN continues as the long-running owner of Telegram intake and project
   state.
3. At least two checkpoint events resume the same stored Codex supervision
   thread across separate user messages or service events.
4. A permitted CGKN repair produces a bounded diff, passes its required tests,
   and records a repair receipt before resume.
5. An impermissible candidate/evidence/package/delivery action is rejected.
6. Supervisor loss, CGKN crash, and thread discontinuity remain visible and do
   not silently bypass a checkpoint.
7. The reviewed Provider and sole `local_packager` delivery route remain
   unchanged.

Until those checks exist, persistent supervision is `NOT_EVALUATED` even when
the architecture document and request-scoped Codex adapters are present.

## 11. Current migration boundary

The existing request-scoped, ephemeral, read-only Codex design adapter is
retained for migration compatibility only. It is not a public runtime profile,
must not run inside the persistent supervisor profile, and is not the
persistent supervisor defined here.

The first persistent runtime increment now provides:

- `scripts/cgkn_supervision_protocol.py` for secret-redacted hash-linked
  checkpoints, result validation, cursor state, release lookup, and service
  heartbeat;
- `scripts/cgkn_runtime_supervisor.py` for Telegram-service start/attachment,
  health/restart state, one stored local Codex thread, and `codex exec resume`;
- an opt-in Telegram Provider-start gate that waits for the matching `observe`
  or `resume` result and then auto-resumes the unchanged Provider handoff;
- observational Provider-success and advisory Provider-failure checkpoints.

The current increment deliberately keeps the Codex assessment thread
read-only. A `repair_cgkn` result is validated and moves the host to
`waiting_repair_executor`; it does not mutate the repository. The next
implementation increment must add an isolated governed repair executor,
before/after diff ownership checks, fixed regression profiles, repair receipts,
and bounded restart release. The existing ephemeral design adapter remains a
transitional specialist until product-design checkpoints are projected through
the persistent supervisor thread.

## 12. Reference

OpenAI's Codex SDK documentation states that applications can control Codex
programmatically and can start, continue, and resume local Codex threads. That
capability supports the persistent-thread adapter described here; it does not
change CGKN's authority boundaries:

- https://developers.openai.com/codex/sdk
