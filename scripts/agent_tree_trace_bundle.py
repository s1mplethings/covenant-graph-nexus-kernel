from __future__ import annotations

import pathlib
import zipfile
from typing import Any

try:
    from agent_tree_contracts import DEFAULT_EVAL_DIR, write_json
except ModuleNotFoundError:  # pragma: no cover
    from scripts.agent_tree_contracts import DEFAULT_EVAL_DIR, write_json


def write_project_tree(project_dir: str | pathlib.Path, out_dir: str | pathlib.Path) -> pathlib.Path:
    project = pathlib.Path(project_dir)
    lines: list[str] = []
    for path in sorted(project.rglob("*")) if project.exists() else []:
        rel = path.relative_to(project).as_posix()
        lines.append(f"{rel}/" if path.is_dir() else rel)
    target = pathlib.Path(out_dir) / "project_tree.txt"
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return target


def create_trace_bundle(
    *,
    out_dir: str | pathlib.Path = DEFAULT_EVAL_DIR,
    project_dir: str | pathlib.Path | None = None,
    final_verdict: dict[str, Any] | None = None,
) -> pathlib.Path:
    out = pathlib.Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    if project_dir is not None:
        write_project_tree(project_dir, out)
    verdict = final_verdict or {"verdict": "NEEDS_REWORK"}
    write_json(out / "final_verdict.json", verdict)
    index = (
        "# Agent Tree Trace Bundle\n\n"
        "This bundle records the controlled agent-tree lane only. It is not proof that the real provider lane passed.\n"
    )
    (out / "00_INDEX.md").write_text(index, encoding="utf-8")

    bundle = out / "agent_tree_trace_bundle.zip"
    source_files = [
        "00_INDEX.md",
        "shared_context.json",
        "agent_build_dag.json",
        "agent_actions.jsonl",
        "feedback_tasks.jsonl",
        "project_tree.txt",
        "final_verdict.json",
    ]
    with zipfile.ZipFile(bundle, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name in source_files:
            path = out / name
            if path.exists():
                zf.write(path, name)
        for folder in ("checkpoints", "contract_checks", "local_contexts"):
            root = out / folder
            if not root.exists():
                continue
            for path in sorted(root.rglob("*")):
                if path.is_file():
                    zf.write(path, path.relative_to(out).as_posix())
        if project_dir is not None:
            project = pathlib.Path(project_dir)
            for path in sorted(project.rglob("*")) if project.exists() else []:
                if path.is_file():
                    zf.write(path, f"08_generated_project/{path.relative_to(project).as_posix()}")
        layout_map = {
            "01_shared_context/shared_context.json": out / "shared_context.json",
            "02_reducer/local_contexts/": None,
            "03_goal_alignment/goal_alignment.json": out / "goal_alignment.json",
            "04_build_dag/agent_build_dag.json": out / "agent_build_dag.json",
            "05_agent_actions/agent_actions.jsonl": out / "agent_actions.jsonl",
            "07_feedback/feedback_tasks.jsonl": out / "feedback_tasks.jsonl",
            "10_final_verdict/final_verdict.json": out / "final_verdict.json",
        }
        for arcname, path in layout_map.items():
            if path is None:
                continue
            if path.exists():
                zf.write(path, arcname)
        for folder, prefix in (("checkpoints", "06_checkpoints"), ("contract_checks", "09_contract_checks")):
            root = out / folder
            if root.exists():
                for path in sorted(root.rglob("*")):
                    if path.is_file():
                        zf.write(path, f"{prefix}/{path.relative_to(root).as_posix()}")
        reducer_root = out / "local_contexts"
        if reducer_root.exists():
            for path in sorted(reducer_root.rglob("*")):
                if path.is_file():
                    zf.write(path, f"02_reducer/local_contexts/{path.relative_to(reducer_root).as_posix()}")
    return bundle
