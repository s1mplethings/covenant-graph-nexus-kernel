# Conversation Product Surface

Conversation is a read-only query and answer surface over the existing CGNK
knowledge system. It is not another planner, agent, RAG store, runtime, or
thread-truth authority.

The production path is:

```text
ConversationRequest
  -> cgnk_knowledge.retrieve_relevant_knowledge
  -> localized evidence selection
  -> optional fidelity-driven child expansion
  -> qualified cheap Provider answer
  -> ConversationResponse + evidence + provenance
```

The common executable boundary is `conversation.answer@1.0`, exposed by
`ConversationExecutor` and the MCP tool `cgkn_conversation`. The request needs
only a query plus the server's project root. Optional thread identity is
correlation metadata only; it is not state authority. Retrieval constraints
are bounded and public-safe.

The response distinguishes `MODEL_GENERATED_ANSWER`, `EVIDENCE_ONLY`, and no
answer. Its semantic statuses are `ANSWERED`, `EVIDENCE_ONLY`,
`INSUFFICIENT_EVIDENCE`, `PROVIDER_UNAVAILABLE`, and `INVALID_REQUEST`.
Evidence is supplied to the model as untrusted data. Every model claim must
cite a selected evidence identity, and invented identities cause deterministic
fallback.

Summaries are indexes, not source replacements. Queries that depend on exact
bytes, ordering, versions, boundaries, identifiers, negative observations, or
transport details trigger a bounded expansion of only the selected summary's
referenced raw evidence. Missing or malformed fidelity metadata causes refusal.

Conversation never writes the ProjectKnowledgePack. Provider unavailability
with relevant evidence produces an evidence-only response; no relevant
evidence produces an insufficient-evidence response without calling a model.
The default answer route remains the existing qualified cheap Worker route.

Use `scripts/run_cgnk_evaluation.py --profile server-formal` for protocol and
fallback checks, `--profile conversation-e2e` for one real product-surface
path, and `--profile conversation-structure-eval` for the fixed ten-case C1
flat-complete versus C2 structured comparison.
