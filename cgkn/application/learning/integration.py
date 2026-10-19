from __future__ import annotations

import os
import json
import pathlib
from dataclasses import replace
from typing import Any

from cgkn.providers import CompletionClient, ProviderCompletion

from .context import GenerationContextAssembler
from .contracts import GenerationRequest, GenerationResult, LessonQuery, canonical_hash
from .query import StoreLessonReader
from .store import FileLessonStore, NoOpLessonReader


class ProductionGenerationClient:
    def __init__(
        self,
        client: CompletionClient,
        reader: Any,
        *,
        store: FileLessonStore | None = None,
        max_provider_calls: int | None = None,
    ):
        self.client, self.reader, self.store = client, reader, store
        self.max_provider_calls = max_provider_calls
        self.provider_call_count = 0
        self.assembler = GenerationContextAssembler(reader)

    def generate(self, request: GenerationRequest) -> GenerationResult:
        disabled = request.lesson_policy == "DISABLED_BY_POLICY"
        if isinstance(self.reader, NoOpLessonReader) and not disabled:
            raise ValueError("production generation cannot use NoOp lessons unless DISABLED_BY_POLICY")
        authority_hash = canonical_hash({"goal": request.goal, "contract": request.contract, "policy": request.dependency_risk_policy})
        query = LessonQuery(
            request.task_class, request.operation, request.capability_ref, request.provider_id,
            request.project_id, _failure_domain(request.failure_evidence), authority_snapshot_hash=authority_hash,
            run_id=request.run_id,
        )
        reader = NoOpLessonReader() if disabled else self.reader
        assembler = GenerationContextAssembler(reader)
        context = assembler.assemble(
            goal=request.goal, contract=request.contract, current_state=request.state,
            dependency_risk_policy=request.dependency_risk_policy,
            failure_evidence=request.failure_evidence, lesson_query=query,
            allowed_actions=request.allowed_actions, forbidden_actions=request.forbidden_actions,
        )
        if request.projected_prompt is None:
            prompt = assembler.render_prompt(context)
        else:
            payload = dict(request.projected_prompt)
            payload["lessons"] = [
                {"lesson_id": lesson_id, "revision": revision, "guidance": guidance, "avoid": avoid}
                for lesson_id, revision, guidance, avoid in zip(
                    context.lesson_context.lesson_ids, context.lesson_context.lesson_revisions,
                    context.lesson_context.bounded_guidance, context.lesson_context.bounded_avoid,
                )
            ]
            prompt = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        if self.max_provider_calls is not None and self.provider_call_count >= self.max_provider_calls:
            raise RuntimeError(f"PROVIDER_CALL_LIMIT_EXCEEDED:{self.max_provider_calls}")
        self.provider_call_count += 1
        model_config = replace(request.model_config, task_class=request.task_class, operation=request.operation)
        completion = self.client.complete(
            system=request.system, user=prompt, schema_name=request.schema_name,
            schema=request.schema, config=model_config,
        )
        usage = dict(completion.usage) | {
            "lesson_snapshot_hash": context.lesson_context.lesson_snapshot_hash,
            "applied_lesson_ids": list(context.lesson_context.lesson_ids),
            "lesson_context_chars": context.lesson_context.context_chars,
            "generation_context_hash": context.context_hash,
            "prompt_projection_hash": request.prompt_projection_hash,
        }
        enriched = ProviderCompletion(
            completion.text, completion.model, completion.request_id, usage, completion.attempts,
            completion.selection_receipt,
        )
        return GenerationResult(enriched, context.lesson_context.lesson_snapshot_hash, context.lesson_context.lesson_ids, context.lesson_context.context_chars, context.context_hash)


def default_production_client(client: CompletionClient, *, artifact_root: pathlib.Path | str | None = None) -> ProductionGenerationClient:
    configured = pathlib.Path(artifact_root or os.environ.get("CGKN_LEARNING_ARTIFACT_ROOT", ".cgkn")).resolve()
    store = FileLessonStore(configured)
    return ProductionGenerationClient(client, StoreLessonReader(store), store=store)


def disabled_generation_client(client: CompletionClient) -> ProductionGenerationClient:
    return ProductionGenerationClient(client, NoOpLessonReader())


def _failure_domain(value: Any) -> str:
    if isinstance(value, dict):
        return str(value.get("failure_domain", ""))
    return str(getattr(value, "failure_domain", "") or "")


def lesson_aware_messages(
    messages: list[dict[str, str]], *, task_class: str, operation: str,
    project_id: str = "", capability_ref: str = "", provider_id: str = "",
    artifact_root: pathlib.Path | str | None = None,
) -> tuple[list[dict[str, str]], dict[str, Any]]:
    """Adapter for the reviewed compatibility transport without creating a second route."""
    if not messages:
        raise ValueError("production Provider messages require user content")
    # Compatibility callers may provide only the user turn. Normalize that
    # shape before learning projection so transport selection and budgeting
    # remain downstream of the reviewed context boundary.
    normalized_messages = [dict(item) for item in messages]
    if len(normalized_messages) == 1:
        normalized_messages.insert(0, {"role": "system", "content": ""})
    try:
        payload: Any = __import__("json").loads(str(normalized_messages[-1].get("content", "")))
    except Exception:
        payload = {"raw_request": str(normalized_messages[-1].get("content", ""))}
    configured = pathlib.Path(artifact_root or os.environ.get("CGKN_LEARNING_ARTIFACT_ROOT", ".cgkn")).resolve()
    store = FileLessonStore(configured); reader = StoreLessonReader(store); assembler = GenerationContextAssembler(reader)
    authority_hash = canonical_hash(payload)
    context = assembler.assemble(
        goal=payload, contract={}, current_state={}, dependency_risk_policy={}, failure_evidence={},
        lesson_query=LessonQuery(task_class, operation, capability_ref, provider_id, project_id, authority_snapshot_hash=authority_hash),
        forbidden_actions=("contract_change", "security_policy_change", "hidden_acceptance"),
    )
    updated = normalized_messages
    rendered_prompt = json.loads(assembler.render_prompt(context))
    # render_prompt exposes goal keys at the top level for native generation
    # clients. The compatibility adapter already carries the same goal under
    # AUTHORITATIVE CONTRACT, so remove only those exact duplicates to keep
    # legacy request sizes bounded without dropping facts.
    if isinstance(payload, dict):
        for key in payload:
            rendered_prompt.pop(str(key), None)
    updated[-1]["content"] = json.dumps(rendered_prompt, ensure_ascii=False, sort_keys=True)
    return updated, {
        "lesson_snapshot_hash": context.lesson_context.lesson_snapshot_hash,
        "applied_lesson_ids": list(context.lesson_context.lesson_ids),
        "lesson_context_chars": context.lesson_context.context_chars,
        "generation_context_hash": context.context_hash,
    }

