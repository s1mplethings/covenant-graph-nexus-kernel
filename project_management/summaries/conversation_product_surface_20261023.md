# Conversation Product Surface and Architecture Convergence

Iteration `ITER-CGNK-CONVERSATION-PRODUCT-SURFACE-AND-ARCHITECTURE-CONVERGENCE-043` closed on source commit `7320040abef270fd0dbf98ff5e80218ec1204e50` (tree `348979a9f7ec9ea7b158ddd3ef803349a03083c4`).

## Outcome

- Gap classification: `E_WITH_F_MISSING_SURFACE`. The repository already had durable knowledge, retrieval, context-pack, and formal MCP authorities; it lacked a user-facing grounded answer capability and server route.
- Added `conversation.answer@1.0` as a read-only Component/Block capability and `cgkn_conversation` as the formal server surface. No second store, retriever, planner, runtime, or state authority was introduced.
- Answers distinguish model-generated text from evidence-only fallback, validate every claim reference, expose provenance, refuse no-evidence and contradictory-evidence cases, and treat retrieved content as untrusted data.
- Summary nodes are retrieval indexes. Exact/order/version/boundary questions can expand only bounded referenced raw evidence.

## Formal and live evidence

- Formal server: PASS for boot, readiness, discovery/specs, guards, supported invocation, malformed input, timeout, provider unavailable, provider recovery, Conversation answer, evidence-only fallback, no-evidence refusal, provenance, restart, security, and unsupported rejection.
- Real Conversation E2E: PASS through `ProjectKnowledgePack -> retrieve_relevant_knowledge -> ConversationService -> evidence/provenance`.
- Fixed comparison: 10 questions, 20 route runs, one corpus/model/rubric/answer budget. C1 flat-complete and C2 structured both achieved 100% accuracy, grounded claims, correct abstention, and correct provenance.
- C1: 17,329 input tokens, 530 output tokens, 130 retrieved nodes, 117 irrelevant nodes, 0 raw expansions, 11,384 ms aggregate latency.
- C2: 4,382 input tokens, 501 output tokens, 21 retrieved nodes, 8 irrelevant nodes, 2 targeted raw expansions, 8,581 ms aggregate latency.
- C2 reduced input tokens by 74.71% and irrelevant-context ratio by 57.67% without accuracy loss. `conversation_structure_benefit = PROVEN_DIRECTIONALLY`; no statistical-significance claim is made.
- Final live ledger: 19 successful calls, 22,583 input tokens, 1,155 output tokens, complete reported usage, estimated USD 0.00408045 using the previously audited price snapshot.

## Architecture convergence

- KEEP: cheap qualified executor routing; structured evidence/knowledge retrieval; read-only Conversation; interface and evidence guards.
- KEEP for reliability, not token claims: incremental materialization (`NEUTRAL`).
- SIMPLIFY: Blueprint retains functional contract value, but its measured efficiency remains `HARMFUL_DIRECTIONALLY`.
- COLLAPSE_CANDIDATE: strong role separation, because its measured benefit remains `HARMFUL_DIRECTIONALLY`.
- REMOVE_CANDIDATE: any duplicate planner, retriever, store, runtime, or project-state authority.
- Multi-Agent: `NOT_RECOMMENDED_CURRENT_EVIDENCE`. Formal Server PASS does not override the lack of demonstrated orchestration benefit.

## Regression

- compileall and product/kernel/test/completeness/freshness gates: PASS.
- static, unit, boundary, fault, security, local-functional, full-core, active-repository: PASS.
- collection: 3,022.
- full repository: 2,671 passed, 351 skipped, 0 failed, 0 errors.
- application suite: 471 passed, 1 skipped, 0 failed, 0 errors.

## Next phase recommendation

Prioritize Conversation usability and knowledge update/internalization policy, then retrieval scaling and Blueprint simplification. Defer Multi-Agent until a real parallelism or coordination bottleneck is measured.
