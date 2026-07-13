from __future__ import annotations

import pathlib
import zipfile
from typing import Any

try:
    import acceptance_verifier
except ModuleNotFoundError:  # pragma: no cover
    from scripts import acceptance_verifier  # type: ignore

try:
    from agent_tree_contracts import read_json, read_jsonl, write_json
    from agent_tree_registry import render_tree
except ModuleNotFoundError:  # pragma: no cover
    from scripts.agent_tree_contracts import read_json, read_jsonl, write_json
    from scripts.agent_tree_registry import render_tree


def _write_project_tree(project_dir: pathlib.Path, out_dir: pathlib.Path) -> None:
    lines = []
    for path in sorted(project_dir.rglob("*")) if project_dir.exists() else []:
        rel = path.relative_to(project_dir).as_posix()
        lines.append(f"{rel}/" if path.is_dir() else rel)
    (out_dir / "project_tree.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")


def create_growth_trace_bundle(*, out_dir: str | pathlib.Path, project_dir: str | pathlib.Path, final_verdict: dict[str, Any]) -> pathlib.Path:
    out = pathlib.Path(out_dir)
    project = pathlib.Path(project_dir)
    _write_project_tree(project, out)
    acceptance_verifier.write_canonical_verdict(out / "final_verdict.json", final_verdict)
    registry = read_json(out / "agent_tree_registry.json", {})
    spawns = read_jsonl(out / "spawn_actions.jsonl")
    leaves = []
    for contract_path in sorted((out / "scope_contracts").glob("*.json")) if (out / "scope_contracts").exists() else []:
        contract = read_json(contract_path, {})
        if contract.get("allowed_files") and "Leaf" in str(contract.get("role", "")):
            leaves.append(f"- {contract['agent_id']}: {', '.join(contract['allowed_files'])}")
    index = [
        "# Dynamic Agent Tree Trace Bundle",
        "",
        "Initial registry contains only `main_agent`.",
        "",
        "## Spawn Summary",
        *[f"- {item['action_id']}: {item['parent_agent']} -> {item['new_agent_id']} ({item['role']}, depth {item['depth']})" for item in spawns],
        "",
        "## Final Tree",
        "```text",
        render_tree(registry),
        "```",
        "",
        "## Leaf File Ownership",
        *leaves,
        "",
        f"Budget violation: {any(not item.get('budget_check', {}).get('allowed', True) for item in spawns)}",
        f"Scope violation: {bool(read_jsonl(out / 'feedback_tasks.jsonl')) and any('scope_violation' in str(item) for item in read_jsonl(out / 'feedback_tasks.jsonl'))}",
        f"Final controlled dynamic lane verdict: {final_verdict.get('verdict')}",
    ]
    (out / "00_INDEX.md").write_text("\n".join(index) + "\n", encoding="utf-8")
    bundle = out / "dynamic_agent_tree_trace_bundle.zip"
    with zipfile.ZipFile(bundle, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        top_files = [
            "00_INDEX.md",
            "start_state.md",
            "start_state.json",
            "shared_context.json",
            "goal_alignment.json",
            "agent_tree_registry_initial.json",
            "agent_tree_registry.json",
            "growth_budget.json",
            "spawn_actions.jsonl",
            "leaf_build_actions.jsonl",
            "feedback_tasks.jsonl",
            "project_tree.txt",
            "final_verdict.json",
        ]
        for name in top_files:
            path = out / name
            if path.exists():
                zf.write(path, name)
        folder_map = {
            "01_start_state": ["start_state.md", "start_state.json"],
            "02_shared_context": ["shared_context.json"],
            "03_reducer": [],
            "04_registry": ["agent_tree_registry_initial.json", "agent_tree_registry.json"],
            "05_spawn_actions": ["spawn_actions.jsonl"],
            "07_leaf_build_actions": ["leaf_build_actions.jsonl"],
            "10_feedback": ["feedback_tasks.jsonl"],
            "13_final_verdict": ["final_verdict.json"],
        }
        for prefix, names in folder_map.items():
            for name in names:
                path = out / name
                if path.exists():
                    zf.write(path, f"{prefix}/{name}")
        for folder, prefix in (
            ("local_contexts", "03_reducer/local_contexts"),
            ("scope_contracts", "06_scope_contracts"),
            ("checkpoints", "08_checkpoints"),
            ("merge_results", "09_merge_results"),
            ("contract_checks", "12_contract_checks"),
        ):
            root = out / folder
            if root.exists():
                for path in sorted(root.rglob("*")):
                    if path.is_file():
                        zf.write(path, f"{prefix}/{path.relative_to(root).as_posix()}")
        for path in sorted(project.rglob("*")) if project.exists() else []:
            if path.is_file():
                zf.write(path, f"11_generated_project/{path.relative_to(project).as_posix()}")
    return bundle
