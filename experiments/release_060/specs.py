"""Frozen generated-original project-family specifications for ITER-060."""

from __future__ import annotations

from collections import Counter, defaultdict, deque
import hashlib
import json
from typing import Any, Mapping, Sequence

from .contracts import (
    ComplexityTier,
    EpisodeMode,
    EpisodeSpec,
    ProjectFamilySpec,
    ProjectType,
    canonical_hash,
)


def _oracle(operation: str, value: Any) -> Any:
    if operation == "canonicalize":
        return value
    if operation == "select_even":
        return [item for item in value if isinstance(item, int) and item % 2 == 0]
    if operation == "deduplicate":
        seen: set[str] = set()
        output = []
        for item in value:
            key = json.dumps(item, ensure_ascii=False, sort_keys=True)
            if key not in seen:
                seen.add(key); output.append(item)
        return output
    if operation == "group_sum":
        totals: dict[str, int] = defaultdict(int)
        for item in value:
            totals[str(item["group"])] += int(item["value"])
        return dict(sorted(totals.items()))
    if operation == "count_levels":
        return dict(sorted(Counter(str(item["level"]).upper() for item in value).items()))
    if operation == "migrate_record":
        result = dict(value)
        if "old_name" in result:
            result["name"] = result.pop("old_name")
        result["schema_version"] = 2
        return result
    if operation == "merge_config":
        result = dict(value.get("base") or {})
        for key, item in dict(value.get("override") or {}).items():
            if isinstance(result.get(key), dict) and isinstance(item, dict):
                result[key] = {**result[key], **item}
            else:
                result[key] = item
        return result
    if operation == "index_headings":
        seen: Counter[str] = Counter(); output = []
        for heading in value:
            slug = "-".join("".join(ch.lower() if ch.isalnum() else " " for ch in str(heading)).split())
            suffix = seen[slug]; seen[slug] += 1
            output.append({"heading": heading, "slug": slug if suffix == 0 else f"{slug}-{suffix}"})
        return output
    if operation == "extract_refs":
        return sorted({str(item).strip() for item in value if str(item).strip()})
    if operation == "normalize_paths":
        return ["/".join(part for part in str(item).replace("\\", "/").split("/") if part not in {"", "."}) for item in value]
    if operation == "numeric_summary":
        numbers = [float(item) for item in value]
        return {"count": len(numbers), "sum": sum(numbers), "min": min(numbers) if numbers else None, "max": max(numbers) if numbers else None}
    if operation == "window_average":
        width = int(value["width"]); numbers = [float(item) for item in value["values"]]
        return [sum(numbers[index:index + width]) / width for index in range(max(0, len(numbers) - width + 1))]
    if operation == "validate_records":
        required = tuple(value.get("required") or ())
        errors = []
        for index, item in enumerate(value.get("records") or ()): 
            missing = sorted(key for key in required if key not in item)
            if missing: errors.append({"index": index, "missing": missing})
        return {"valid": not errors, "errors": errors}
    if operation == "toposort":
        deps = {str(key): set(map(str, items)) for key, items in dict(value).items()}
        nodes = set(deps)
        for items in deps.values(): nodes.update(items)
        ready = deque(sorted(node for node in nodes if not deps.get(node, set())))
        output = []
        while ready:
            node = ready.popleft(); output.append(node)
            for candidate in sorted(nodes - set(output)):
                if node in deps.get(candidate, set()): deps[candidate].remove(node)
                if not deps.get(candidate, set()) and candidate not in ready: ready.append(candidate)
        return output if len(output) == len(nodes) else {"error": "cycle"}
    if operation == "checksums":
        return {key: hashlib.sha256(str(item).encode("utf-8")).hexdigest() for key, item in sorted(dict(value).items())}
    if operation == "diagnose":
        mapping = {"timeout": "TRANSIENT", "permission": "CONFIGURATION", "syntax": "SOURCE", "missing": "DEPENDENCY"}
        return [mapping.get(str(item).casefold(), "UNKNOWN") for item in value]
    if operation == "retry_plan":
        return [item["id"] for item in sorted(value, key=lambda item: (int(item.get("attempts", 0)), str(item["id"]))) if int(item.get("attempts", 0)) < int(item.get("max", 1))]
    if operation == "version_trace":
        current = None; history = []
        for item in value:
            if item.get("supersedes") == current or current is None:
                current = item["version"]; history.append(current)
        return {"current": current, "history": history}
    if operation == "join_records":
        right = {item["id"]: item for item in value.get("right", ())}
        return [{**item, **{key: val for key, val in right.get(item["id"], {}).items() if key != "id"}} for item in value.get("left", ()) if item["id"] in right]
    if operation == "schedule":
        return [item["id"] for item in sorted(value, key=lambda item: (-int(item.get("priority", 0)), str(item["id"])))]
    raise ValueError(f"unsupported operation {operation}")


_PUBLIC_VALUES: dict[str, Any] = {
    "canonicalize": {"z": 1, "a": {"n": 2}},
    "select_even": [5, 2, 4, 7],
    "deduplicate": ["a", "b", "a", "c"],
    "group_sum": [{"group": "b", "value": 2}, {"group": "a", "value": 3}, {"group": "b", "value": 4}],
    "count_levels": [{"level": "info"}, {"level": "ERROR"}, {"level": "Info"}],
    "migrate_record": {"old_name": "Ada", "enabled": True},
    "merge_config": {"base": {"app": {"port": 1, "host": "x"}}, "override": {"app": {"port": 2}}},
    "index_headings": ["Overview", "API Guide", "API Guide"],
    "extract_refs": ["doc:b", " doc:a ", "doc:b"],
    "normalize_paths": ["./a\\b", "c//d"],
    "numeric_summary": [2, 4, 7],
    "window_average": {"width": 2, "values": [1, 3, 5]},
    "validate_records": {"required": ["id", "name"], "records": [{"id": 1}, {"id": 2, "name": "b"}]},
    "toposort": {"build": ["fetch"], "test": ["build"], "fetch": []},
    "checksums": {"b.txt": "beta", "a.txt": "alpha"},
    "diagnose": ["timeout", "syntax", "other"],
    "retry_plan": [{"id": "b", "attempts": 1, "max": 1}, {"id": "a", "attempts": 0, "max": 2}],
    "version_trace": [{"version": "1", "supersedes": None}, {"version": "2", "supersedes": "1"}],
    "join_records": {"left": [{"id": 1, "name": "a"}, {"id": 2, "name": "b"}], "right": [{"id": 2, "score": 9}]},
    "schedule": [{"id": "b", "priority": 1}, {"id": "a", "priority": 2}],
}


_PRIVATE_VALUES: dict[str, Any] = {
    "canonicalize": {"nested": [{"b": 2, "a": 1}], "empty": {}},
    "select_even": [-2, -1, 0, 9, 12],
    "deduplicate": [{"x": 1}, {"x": 1}, {"x": 2}],
    "group_sum": [{"group": "x", "value": -2}, {"group": "x", "value": 5}, {"group": "y", "value": 0}],
    "count_levels": [],
    "migrate_record": {"name": "Grace", "schema_version": 2},
    "merge_config": {"base": {"a": 1, "nested": {"x": 1}}, "override": {"b": 2, "nested": {"y": 3}}},
    "index_headings": ["Hello, World!", "Hello World", "Deep/API"],
    "extract_refs": ["", "x", " y", "x"],
    "normalize_paths": ["a/b", "./x///y\\z"],
    "numeric_summary": [],
    "window_average": {"width": 3, "values": [0, 3, 6, 9]},
    "validate_records": {"required": ["id"], "records": [{"id": 0}, {}]},
    "toposort": {"a": ["b"], "b": ["a"]},
    "checksums": {"empty": "", "unicode": "雪"},
    "diagnose": ["permission", "missing", "TIMEOUT"],
    "retry_plan": [{"id": "z", "attempts": 1, "max": 3}, {"id": "a", "attempts": 0, "max": 1}],
    "version_trace": [{"version": "1", "supersedes": None}, {"version": "3", "supersedes": "wrong"}],
    "join_records": {"left": [{"id": "x", "v": 1}], "right": [{"id": "x", "v": 2, "extra": True}]},
    "schedule": [{"id": "z", "priority": 0}, {"id": "a", "priority": 0}],
}


def _case(package: str, operation: str, value: Any, *, suffix: str) -> Mapping[str, Any]:
    input_name = f"{suffix}-input.json"; output_name = f"{suffix}-output.json"
    return {
        "files": {input_name: json.dumps(value, ensure_ascii=False)},
        "steps": [{
            "argv": [operation, input_name, output_name],
            "code": 0,
            "file_json": {"path": output_name, "value": _oracle(operation, value)},
        }],
        "package": package,
    }


def _state_case(package: str, operation: str, *, private: bool) -> Mapping[str, Any]:
    if operation == "counter_state":
        deltas = (4, -1) if private else (2, 3)
        expected = (4, 3) if private else (2, 5)
    elif operation == "dedup_state":
        deltas = ("x", "x") if private else ("a", "b")
        expected = (True, False) if private else (True, True)
    else:
        raise ValueError(operation)
    files = {f"state-input-{index}.json": json.dumps({"value": value}, ensure_ascii=False) for index, value in enumerate(deltas, 1)}
    steps = []
    for index, wanted in enumerate(expected, 1):
        steps.append({
            "argv": [operation, f"state-input-{index}.json", f"state-output-{index}.json", "--state", "state.json"],
            "code": 0,
            "file_json": {"path": f"state-output-{index}.json", "value": {"result": wanted}},
        })
    return {"files": files, "steps": steps, "package": package, "restart_between_steps": True}


def _episode(package: str, family_id: str, index: int, operation: str, mode: str, paths: Sequence[str]) -> EpisodeSpec:
    stateful = operation in {"counter_state", "dedup_state"}
    public_case = _state_case(package, operation, private=False) if stateful else _case(package, operation, _PUBLIC_VALUES[operation], suffix="public")
    private_case = _state_case(package, operation, private=True) if stateful else _case(package, operation, _PRIVATE_VALUES[operation], suffix="private")
    behavior = (
        f"Implement the {operation} command with the exact public examples. "
        "The command is invoked as `python -m PACKAGE OP INPUT OUTPUT`; stateful commands also accept `--state FILE`. "
        "Read UTF-8 JSON, write deterministic UTF-8 JSON, use stderr and exit code 2 for invalid input, and never use network or shell."
    )
    return EpisodeSpec(
        episode_id=f"{family_id}-E{index}", mode=mode, public_instruction=behavior,
        required_paths=tuple(paths),
        public_acceptance=(f"{operation} matches the canonical public examples", "invalid input fails closed without overwriting output", "all prior episode behavior remains valid unless explicitly superseded"),
        public_cases=(public_case,), private_cases=(private_case,), version=f"{index}.0",
        state_dependencies=tuple(f"{family_id}-E{prior}" for prior in range(1, index)) if index > 1 else (),
        supersedes=(f"{family_id}-E{index-1}",) if mode == EpisodeMode.VERSION_CHANGE.value and index > 1 else (),
        controlled_mutation={"operation": operation, "mutation": mode} if mode != EpisodeMode.FROM_SCRATCH.value else {},
    )


def _paths(package: str, tier: str, episode_count: int) -> tuple[tuple[str, ...], ...]:
    base = [f"{package}/__init__.py", f"{package}/__main__.py", f"{package}/core.py"]
    extras = [
        f"{package}/models.py", f"{package}/storage.py", f"{package}/validation.py",
        f"{package}/pipeline.py", f"{package}/provenance.py", f"{package}/recovery.py",
        f"{package}/migration.py", f"{package}/diagnostics.py", f"{package}/interfaces.py",
    ]
    final_source_count = {ComplexityTier.LOW.value: 3, ComplexityTier.MEDIUM.value: 6, ComplexityTier.HIGH.value: 10}[tier]
    source_paths = base + extras[: max(0, final_source_count - len(base))]
    output = []
    for index in range(episode_count):
        count = max(3, round(final_source_count * (index + 1) / episode_count))
        output.append(tuple(source_paths[:count] + ["README.md", "pyproject.toml"]))
    return tuple(output)


def _modes(tier: str, count: int, flags: frozenset[str]) -> tuple[str, ...]:
    modes = [EpisodeMode.FROM_SCRATCH.value] + [EpisodeMode.FEATURE_EXTENSION.value] * (count - 1)
    if "migration" in flags and count >= 3: modes[2] = EpisodeMode.VERSION_CHANGE.value
    if "repair" in flags and count >= 2: modes[1] = EpisodeMode.BUG_REPAIR.value
    if "restart" in flags and count >= 4: modes[3] = EpisodeMode.RESTART_RESUME.value
    if "state" in flags and count >= 2: modes[-1] = EpisodeMode.STATEFUL_CONTINUATION.value
    return tuple(modes)


def _family(
    number: int, split: str, tier: str, project_type: str, package: str, goal: str,
    operations: Sequence[str], *, flags: Sequence[str] = (), language: str = "Python",
) -> ProjectFamilySpec:
    family_id = f"PF-060-{number:03d}"
    flag_set = frozenset(flags)
    path_plan = _paths(package, tier, len(operations)); modes = _modes(tier, len(operations), flag_set)
    episodes = tuple(_episode(package, family_id, index, operation, modes[index - 1], path_plan[index - 1]) for index, operation in enumerate(operations, 1))
    final_paths = path_plan[-1]
    source_files = len([path for path in final_paths if path.endswith(".py")])
    state_count = sum(bool(item.state_dependencies) for item in episodes)
    return ProjectFamilySpec(
        family_id=family_id, split=split, complexity=tier, project_type=project_type,
        language=language, package_name=package, public_goal=goal,
        functional_requirements=tuple(f"Support deterministic `{operation}` behavior" for operation in operations),
        constraints=("Python standard library only", "network and shell are forbidden", "UTF-8 JSON interfaces are deterministic", "preserve non-superseded prior behavior"),
        public_interfaces=(f"python -m {package} OP INPUT OUTPUT", f"python -m {package} OP INPUT OUTPUT --state STATE for stateful commands"),
        expected_artifacts=final_paths, episodes=episodes,
        raw_complexity={
            "file_count": source_files, "loc": {"LOW": 120, "MEDIUM": 420, "HIGH": 950}[tier],
            "module_count": source_files, "dependency_count": max(1, source_files - 1),
            "episode_count": len(episodes), "state_dependency_count": state_count,
            "version_count": len(episodes), "repair_rounds": 2 if "repair2" in flag_set else 1 if "repair" in flag_set else 0,
            "capability_count": 5 if "capability" in flag_set else 2, "knowledge_source_count": 3 if "provenance" in flag_set else 1,
        },
        provenance_sensitive="provenance" in flag_set, capability_heavy="capability" in flag_set,
    )


_D = "DEVELOPMENT"; _F = "FORMAL_HOLDOUT"


def _all() -> tuple[ProjectFamilySpec, ...]:
    rows = (
        # Development: four families per tier.  Formal families are distinct tasks.
        (1,_D,"LOW",ProjectType.CLI_FILE_TOOL.value,"tsv_scout","Summarize small tabular extracts without altering the source.",( "numeric_summary",)),
        (2,_D,"LOW",ProjectType.CONFIG_MIGRATION.value,"json_cleanroom","Canonicalize and normalize configuration fragments.",( "canonicalize","normalize_paths")),
        (3,_D,"LOW",ProjectType.LOG_DIAGNOSTIC.value,"level_lens","Count normalized diagnostic levels.",( "count_levels",)),
        (4,_D,"LOW",ProjectType.DOCUMENT_KNOWLEDGE.value,"heading_cards","Build stable heading cards for local notes.",( "index_headings","extract_refs")),
        (5,_D,"MEDIUM",ProjectType.DATA_PIPELINE.value,"record_forge","Validate, filter, and aggregate record batches.",( "validate_records","select_even","group_sum")),
        (6,_D,"MEDIUM",ProjectType.CONFIG_MIGRATION.value,"settings_bridge","Merge and migrate versioned application settings.",( "merge_config","migrate_record","canonicalize"),("migration",)),
        (7,_D,"MEDIUM",ProjectType.LOCAL_SERVICE.value,"counter_port","Maintain restart-safe counters through a local CLI boundary.",( "counter_state","numeric_summary","version_trace"),("state",)),
        (8,_D,"MEDIUM",ProjectType.LIBRARY_PACKAGE.value,"path_ledger","Normalize paths and produce stable content checksums.",( "normalize_paths","checksums","deduplicate"),("provenance",)),
        (9,_D,"HIGH",ProjectType.MULTI_COMPONENT_AUTOMATION.value,"resume_flow","Plan, checkpoint, and resume dependent local work.",( "toposort","schedule","retry_plan","counter_state","version_trace"),("restart","state","repair","capability")),
        (10,_D,"HIGH",ProjectType.DATA_PIPELINE.value,"ledger_etl","Validate, join, aggregate, and version local datasets.",( "validate_records","join_records","group_sum","migrate_record","checksums"),("migration","repair","provenance","capability")),
        (11,_D,"HIGH",ProjectType.LOG_DIAGNOSTIC.value,"incident_atlas","Correlate diagnostics with retry and recovery decisions.",( "count_levels","diagnose","retry_plan","dedup_state","version_trace"),("restart","state","repair2")),
        (12,_D,"HIGH",ProjectType.DOCUMENT_KNOWLEDGE.value,"citation_vault","Index, deduplicate, version, and trace local references.",( "extract_refs","index_headings","deduplicate","checksums","version_trace"),("restart","state","provenance","capability")),
        # Formal LOW: 8 distinct self-contained projects.
        (13,_F,"LOW",ProjectType.CLI_FILE_TOOL.value,"even_export","Filter numeric exports by parity.",( "select_even",)),
        (14,_F,"LOW",ProjectType.DATA_PIPELINE.value,"group_tally","Aggregate grouped integer observations.",( "group_sum","numeric_summary")),
        (15,_F,"LOW",ProjectType.CONFIG_MIGRATION.value,"record_upgrade","Upgrade one legacy record schema.",( "migrate_record",)),
        (16,_F,"LOW",ProjectType.LOG_DIAGNOSTIC.value,"severity_rollup","Roll up case-insensitive log severity labels.",( "count_levels","diagnose")),
        (17,_F,"LOW",ProjectType.DOCUMENT_KNOWLEDGE.value,"reference_sorter","Normalize and sort document references.",( "extract_refs",)),
        (18,_F,"LOW",ProjectType.LOCAL_SERVICE.value,"tiny_counter","Persist a counter across independent process calls.",( "counter_state","numeric_summary"),("state",)),
        (19,_F,"LOW",ProjectType.LIBRARY_PACKAGE.value,"stable_unique","Provide stable structural deduplication.",( "deduplicate",)),
        (20,_F,"LOW",ProjectType.MULTI_COMPONENT_AUTOMATION.value,"priority_order","Order small work batches deterministically.",( "schedule","retry_plan")),
        # Formal MEDIUM: feature, state, migration, repair, and provenance coverage.
        (21,_F,"MEDIUM",ProjectType.CLI_FILE_TOOL.value,"path_manifest","Normalize path inventories and attach checksums.",( "normalize_paths","deduplicate","checksums"),("provenance",)),
        (22,_F,"MEDIUM",ProjectType.DATA_PIPELINE.value,"quality_pipeline","Validate records then aggregate accepted values.",( "validate_records","group_sum","numeric_summary","canonicalize"),("repair",)),
        (23,_F,"MEDIUM",ProjectType.CONFIG_MIGRATION.value,"profile_migrator","Merge layered profiles and migrate their record schema.",( "merge_config","canonicalize","migrate_record"),("migration",)),
        (24,_F,"MEDIUM",ProjectType.LOG_DIAGNOSTIC.value,"failure_triage","Summarize failures and derive a bounded retry plan.",( "count_levels","diagnose","retry_plan"),("repair",)),
        (25,_F,"MEDIUM",ProjectType.DOCUMENT_KNOWLEDGE.value,"doc_registry","Index headings, references, and exact source digests.",( "index_headings","extract_refs","checksums"),("provenance",)),
        (26,_F,"MEDIUM",ProjectType.LOCAL_SERVICE.value,"seen_registry","Remember processed keys across process restarts.",( "dedup_state","counter_state","version_trace"),("state",)),
        (27,_F,"MEDIUM",ProjectType.LIBRARY_PACKAGE.value,"series_window","Provide summaries and moving windows for numeric series.",( "numeric_summary","window_average","canonicalize"),("repair",)),
        (28,_F,"MEDIUM",ProjectType.MULTI_COMPONENT_AUTOMATION.value,"dependency_queue","Validate work, order dependencies, and schedule priority.",( "validate_records","toposort","schedule","retry_plan"),("capability",)),
        # Formal HIGH: four restart families, migrations, multi-round repair, provenance and capabilities.
        (29,_F,"HIGH",ProjectType.LOCAL_SERVICE.value,"durable_job_service","Maintain durable jobs through enqueue, restart, retry, and version transitions.",( "counter_state","schedule","retry_plan","dedup_state","version_trace"),("restart","state","repair2","capability")),
        (30,_F,"HIGH",ProjectType.DATA_PIPELINE.value,"versioned_dataflow","Validate, join, aggregate, migrate, and checksum a versioned pipeline.",( "validate_records","join_records","group_sum","migrate_record","checksums","version_trace"),("migration","repair","provenance","capability")),
        (31,_F,"HIGH",ProjectType.CONFIG_MIGRATION.value,"policy_evolution","Evolve layered configuration while preserving version and provenance traces.",( "merge_config","validate_records","migrate_record","checksums","version_trace"),("restart","migration","state","provenance")),
        (32,_F,"HIGH",ProjectType.LOG_DIAGNOSTIC.value,"recovery_console","Diagnose incidents, schedule recovery, persist seen failures, and resume.",( "count_levels","diagnose","retry_plan","dedup_state","schedule"),("restart","state","repair2","capability")),
        (33,_F,"HIGH",ProjectType.DOCUMENT_KNOWLEDGE.value,"evidence_catalog","Build a versioned, provenance-sensitive catalog of headings and references.",( "index_headings","extract_refs","deduplicate","checksums","version_trace"),("restart","state","provenance")),
        (34,_F,"HIGH",ProjectType.LIBRARY_PACKAGE.value,"dependency_library","Expose validation, dependency ordering, scheduling, and recovery APIs.",( "validate_records","toposort","schedule","retry_plan","version_trace"),("repair","capability")),
        (35,_F,"HIGH",ProjectType.MULTI_COMPONENT_AUTOMATION.value,"checkpoint_automation","Run dependent local stages with checkpoints, retries, and exact evidence.",( "toposort","schedule","counter_state","retry_plan","checksums","version_trace"),("restart","state","repair2","provenance","capability")),
        (36,_F,"HIGH",ProjectType.CLI_FILE_TOOL.value,"migration_workbench","Combine path normalization, configuration migration, validation, and trace output.",( "normalize_paths","merge_config","migrate_record","validate_records","version_trace"),("migration","repair","state")),
    )
    return tuple(_family(*row[:7], flags=row[7] if len(row) > 7 else ()) for row in rows)


_FAMILIES = _all()


def development_families() -> tuple[ProjectFamilySpec, ...]:
    return tuple(item for item in _FAMILIES if item.split == _D)


def formal_families() -> tuple[ProjectFamilySpec, ...]:
    return tuple(item for item in _FAMILIES if item.split == _F)


def full_manifest() -> dict[str, Any]:
    families = [item.public_dict() | {"public_hash": item.public_hash, "private_hash": item.private_hash} for item in _FAMILIES]
    value = {
        "kind": "CGNKITER060ProjectFamilyManifest",
        "schema_version": "1.0",
        "family_count": len(families),
        "development_count": len(development_families()),
        "formal_count": len(formal_families()),
        "families": families,
    }
    value["manifest_hash"] = canonical_hash(value)
    return value
