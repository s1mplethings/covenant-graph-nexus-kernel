from __future__ import annotations

import pathlib
import zipfile
from typing import Any

try:
    import acceptance_verifier
except ModuleNotFoundError:  # pragma: no cover
    from scripts import acceptance_verifier  # type: ignore

try:
    from agent_tree_contracts import read_json, write_json
except ModuleNotFoundError:  # pragma: no cover
    from scripts.agent_tree_contracts import read_json, write_json


def create_long_run_trace_bundle(*, out_dir: str | pathlib.Path, final_verdict: dict[str, Any]) -> pathlib.Path:
    out = pathlib.Path(out_dir)
    acceptance_verifier.write_canonical_verdict(out / "final_verdict.json", final_verdict)
    section_names = {
        "01_start_state": "Start state",
        "02_provider_readiness": "Provider readiness",
        "03_full_pytest_diagnosis": "Full pytest timeout diagnosis",
        "04_phase1_controlled_replay": "Phase 1 controlled replay",
        "05_phase2_real_leaf": "Phase 2 real leaf",
        "06_phase3_mixed_branch": "Phase 3 mixed branch",
        "07_phase4_failure_repair": "Phase 4 failure repair",
        "08_agent_tree_registry": "Agent tree registry",
        "09_spawn_actions": "Spawn actions",
        "10_scope_contracts": "Scope contracts",
        "11_checkpoints": "Checkpoints",
        "12_merge_results": "Merge results",
        "13_feedback_and_repairs": "Feedback and repairs",
        "14_generated_projects": "Generated projects",
        "15_contract_checks": "Contract checks",
        "16_final_verdict": "Final verdict",
    }
    index = [
        "# Dynamic Agent Tree Long-Run Trace Bundle",
        "",
        "Purpose: verify dynamic agent tree control over long chains, scoped real-provider leaf attempts, repair, checkpoints, merges, and traceability.",
        f"Provider ready: {read_json(out / 'provider_readiness.json', {}).get('provider_ready')}",
        f"Phase 0 diagnosis: {read_json(out / 'full_pytest_diagnosis' / 'full_pytest_file_timings.json', {}).get('summary', {}).get('diagnosis_verdict', '')}",
        f"Phase 1 controlled replay: {read_json(out / 'phase1_controlled_replay_result.json', {}).get('verdict', '')}",
        f"Phase 2 real leaf: {read_json(out / 'phase2_real_leaf_result.json', {}).get('classification', '')}",
        f"Phase 3 mixed branch: {read_json(out / 'phase3_mixed_branch_result.json', {}).get('classification', '')}",
        f"Phase 4 failure repair: {read_json(out / 'phase4_failure_repair_result.json', {}).get('verdict', '')}",
        f"Scope violation: {final_verdict.get('scope_violation_detected')}",
        f"Fake success: {final_verdict.get('fake_success_detected')}",
        f"Final verdict: {final_verdict.get('verdict')}",
        f"Final classification: {final_verdict.get('classification')}",
    ]
    (out / "00_INDEX.md").write_text("\n".join(index) + "\n", encoding="utf-8")
    bundle = out / "dynamic_agent_tree_long_run_trace_bundle.zip"
    sections = {
        "01_start_state": ["start_state.md", "start_state.json"],
        "02_provider_readiness": ["provider_readiness.json", "provider_readiness.md"],
        "16_final_verdict": ["final_verdict.json"],
    }
    with zipfile.ZipFile(bundle, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        if (out / "00_INDEX.md").exists():
            zf.write(out / "00_INDEX.md", "00_INDEX.md")
        for prefix, label in section_names.items():
            zf.writestr(f"{prefix}/section_index.md", f"# {label}\n")
        for prefix, names in sections.items():
            for name in names:
                path = out / name
                if path.exists():
                    zf.write(path, f"{prefix}/{name}")
                    zf.write(path, name)
        folder_map = {
            "full_pytest_diagnosis": "03_full_pytest_diagnosis",
            "phase1_controlled_replay": "04_phase1_controlled_replay",
            "phase2_real_leaf": "05_phase2_real_leaf",
            "phase3_mixed_branch": "06_phase3_mixed_branch",
            "phase4_failure_repair": "07_phase4_failure_repair",
        }
        for folder, prefix in folder_map.items():
            root = out / folder
            if root.exists():
                for path in sorted(root.rglob("*")):
                    if path.is_file():
                        zf.write(path, f"{prefix}/{path.relative_to(root).as_posix()}")
        for name in (
            "phase1_controlled_replay_result.json",
            "phase1_controlled_replay_result.md",
            "phase2_real_leaf_result.json",
            "phase2_real_leaf_result.md",
            "phase3_mixed_branch_result.json",
            "phase3_mixed_branch_result.md",
            "phase4_failure_repair_result.json",
            "phase4_failure_repair_result.md",
        ):
            path = out / name
            if path.exists():
                zf.write(path, name)
                if name.startswith("phase1_"):
                    zf.write(path, f"04_phase1_controlled_replay/{name}")
                elif name.startswith("phase2_"):
                    zf.write(path, f"05_phase2_real_leaf/{name}")
                elif name.startswith("phase3_"):
                    zf.write(path, f"06_phase3_mixed_branch/{name}")
                elif name.startswith("phase4_"):
                    zf.write(path, f"07_phase4_failure_repair/{name}")
        for folder, prefix in (
            ("phase1_controlled_replay/agent_tree_registry.json", "08_agent_tree_registry/phase1_agent_tree_registry.json"),
            ("phase1_controlled_replay/spawn_actions.jsonl", "09_spawn_actions/phase1_spawn_actions.jsonl"),
        ):
            path = out / folder
            if path.exists():
                zf.write(path, prefix)
    return bundle
