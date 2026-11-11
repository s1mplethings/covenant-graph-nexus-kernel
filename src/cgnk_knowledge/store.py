from __future__ import annotations

import json
import pathlib
from typing import Any


IMPORTANCE_RANK = {"critical": 0, "high": 1, "medium": 2, "low": 3, "noise": 4}
NEED_RANK = {"needed_now": 0, "needed_later": 1, "reference_only": 2, "unknown": 3, "not_needed": 4}
ACTIVE_BUCKETS = {
    "goal": "active_goals",
    "constraint": "active_constraints",
    "decision": "active_decisions",
    "requirement": "current_requirements",
    "module_mapping": "module_mappings",
    "agent_mapping": "agent_mappings",
    "risk": "risks",
    "open_question": "open_questions",
    "next_step": "next_steps",
    "artifact_ref": "artifact_refs",
    "research_finding": "research_findings",
    "test_result": "test_results",
}


def _sort_key(item: dict[str, Any]) -> tuple[Any, ...]:
    return (
        IMPORTANCE_RANK.get(item.get("importance"), 9),
        NEED_RANK.get(item.get("need_state"), 9),
        str(item.get("type", "")),
        str(item.get("id", "")),
    )


def _sorted_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(items, key=_sort_key)


def _active(item: dict[str, Any]) -> bool:
    return (
        item.get("status", "active") == "active"
        and item.get("retention") != "discard"
        and item.get("review_state") != "rejected"
        and item.get("importance") != "noise"
    )


def rebuild_pack_indexes(pack: dict[str, Any]) -> dict[str, Any]:
    all_items = _sorted_items([dict(row) for row in pack.get("all_items", [])])
    pack["all_items"] = all_items
    for bucket in ACTIVE_BUCKETS.values():
        pack[bucket] = []
    for item in all_items:
        if _active(item):
            bucket = ACTIVE_BUCKETS.get(item.get("type"))
            if bucket:
                pack[bucket].append(item)
    pack["archived_items"] = _sorted_items(
        list({row["id"]: row for row in pack.get("archived_items", []) + [row for row in all_items if row.get("status") == "archived" or row.get("retention") == "archive"]}.values())
    )
    pack["discarded_items"] = _sorted_items(
        list({row["id"]: row for row in pack.get("discarded_items", []) + [row for row in all_items if row.get("retention") == "discard"]}.values())
    )
    return pack


def new_project_knowledge_pack(project: str, pack_id: str | None = None) -> dict[str, Any]:
    pack = {
        "kind": "ProjectKnowledgePack",
        "id": pack_id or f"pkp_{str(project or 'project').lower().replace(' ', '_')}",
        "project": project,
        "version": "1",
        "active_goals": [],
        "active_constraints": [],
        "active_decisions": [],
        "current_requirements": [],
        "module_mappings": [],
        "agent_mappings": [],
        "risks": [],
        "open_questions": [],
        "next_steps": [],
        "artifact_refs": [],
        "research_findings": [],
        "test_results": [],
        "archived_items": [],
        "discarded_items": [],
        "all_items": [],
        "diagnostics": [],
    }
    return rebuild_pack_indexes(pack)


def load_project_knowledge(path: str | pathlib.Path) -> dict[str, Any]:
    data = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    return rebuild_pack_indexes(data)


def save_project_knowledge(path: str | pathlib.Path, pack: dict[str, Any]) -> dict[str, Any]:
    target = pathlib.Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    clean = rebuild_pack_indexes(dict(pack))
    from cgkn.state import FileRunStore
    FileRunStore(target.parent).atomic_json(target, clean)
    return {"kind": "KnowledgeStoreWriteResult", "path": str(target), "pack": clean, "diagnostics": []}


def update_project_knowledge(path, project, items, *, expected_hash=None):
    """Merge under the existing store's OS lock; optional CAS for corrections.

    Writers submit only changed items, never a stale replacement snapshot.
    This is the same ProjectKnowledgePack, not another knowledge authority.
    """
    from cgkn.state import FileRunStore
    from cgkn.state.task_feedback import digest
    target = pathlib.Path(path).resolve()
    store = FileRunStore(target.parent)
    with store.exclusive_file(target.with_suffix(target.suffix + '.lock'), wait_seconds=30):
        current = load_project_knowledge(target) if target.exists() else new_project_knowledge_pack(project)
        if current['project'] != project:
            raise ValueError('knowledge project mismatch')
        if expected_hash is not None and digest(current) != expected_hash:
            raise ValueError('stale knowledge correction')
        changed_ids = {str(i['id']) for i in items}
        existing_ids = {str(i['id']) for i in current['all_items']}
        if changed_ids & existing_ids and expected_hash is None:
            # Identical replay is safe, but revisions require compare-and-swap.
            old = {i['id']: i for i in current['all_items']}
            if any(i['id'] in old and i != old[i['id']] for i in items):
                raise ValueError('knowledge correction requires expected_hash')
        updated = upsert_knowledge_items(current, items)
        return save_project_knowledge(target, updated)


def finalize_reviewed_lesson(path, item_id, acceptance, goal_ids, *, reviewer, expected_hash):
    """Publish an explicitly reviewed lesson only with current trusted checks.

    The reviewer binds the lesson's claim to these goals. A model evaluation
    alone cannot call this publication path with a fabricated PASS dictionary.
    """
    from cgkn.state.acceptance import GoalAcceptance
    from cgkn.state.task_feedback import digest
    if not isinstance(acceptance, GoalAcceptance) or not reviewer or not goal_ids:
        raise ValueError('canonical acceptance and explicit review required')
    if not (acceptance.root / 'provenance_contract.json').is_file():
        raise ValueError('provenance-bound acceptance required')
    goals = {g['id']:g for g in acceptance.view()['goals']}
    if any(g not in goals or goals[g]['verdict'] != 'VERIFIED' for g in goal_ids):
        raise ValueError('lesson validation lacks current verified evidence')
    pack = load_project_knowledge(path)
    item = next(i for i in pack['all_items'] if i['id']==item_id)
    reviewed = {**item, 'review_state':'accepted', 'status':'active',
        'validation': {'reviewer':reviewer, 'project_id':acceptance.project_id,
            'run_id':acceptance.run_id, 'goals':{g:goals[g]['evidence'] for g in goal_ids}},
        'source_refs':list({digest(ref):ref for ref in [*item.get('source_refs',[]),
            *[str(acceptance.root / 'attempts' / goals[g]['evidence']['node_id'] /
                (goals[g]['evidence']['attempt_id']+'.json')) for g in goal_ids]]}.values())}
    return update_project_knowledge(path,pack['project'],[reviewed],expected_hash=expected_hash)


def upsert_knowledge_items(pack: dict[str, Any], items: list[dict[str, Any]]) -> dict[str, Any]:
    out = dict(pack or new_project_knowledge_pack("CGKN"))
    by_id = {str(row.get("id")): dict(row) for row in out.get("all_items", [])}
    diagnostics: list[dict[str, Any]] = []
    for item in items:
        by_id[str(item.get("id"))] = dict(item)
    for item in items:
        for superseded_id in item.get("supersedes", []):
            if superseded_id in by_id:
                by_id[superseded_id]["status"] = "superseded"
                by_id[superseded_id]["review_state"] = "rejected"
                by_id[superseded_id]["need_state"] = "not_needed"
                by_id[superseded_id]["retention"] = "archive"
                by_id[superseded_id]["superseded_by"] = item.get("id")
                diagnostics.append({"code": "CGNK_KNOWLEDGE_SUPERSEDED", "severity": "info", "message": f"{superseded_id} superseded"})
    out["all_items"] = list(by_id.values())
    out["diagnostics"] = list(out.get("diagnostics", [])) + diagnostics
    return rebuild_pack_indexes(out)


def archive_knowledge_item(pack: dict[str, Any], item_id: str, reason: str | None = None) -> dict[str, Any]:
    out = dict(pack)
    for item in out.get("all_items", []):
        if item.get("id") == item_id:
            item["status"] = "archived"
            item["retention"] = "archive"
            item.setdefault("diagnostics", []).append({"code": "CGNK_KNOWLEDGE_SUPERSEDED", "severity": "info", "message": reason or "archived"})
    return rebuild_pack_indexes(out)


def discard_knowledge_item(pack: dict[str, Any], item_id: str, reason: str | None = None) -> dict[str, Any]:
    out = dict(pack)
    for item in out.get("all_items", []):
        if item.get("id") == item_id:
            item["retention"] = "discard"
            item.setdefault("diagnostics", []).append({"code": "CGNK_KNOWLEDGE_DISCARDED", "severity": "info", "message": reason or "discarded"})
    return rebuild_pack_indexes(out)
