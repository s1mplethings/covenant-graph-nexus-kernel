#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import pathlib
import shutil
import sys
from typing import Any

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from cgnk_core import ContractRegistry, SchemaLoader  # noqa: E402
from cgnk_core.schema_loader import load_json  # noqa: E402
from cgnk_ctcp.bridge_review import review_ctcp_bridge  # noqa: E402
from cgnk_ctcp.readiness import check_slice_readiness  # noqa: E402
from cgnk_modules.readiness import build_module_chain_readiness  # noqa: E402

DEFAULT_PROPOSAL = ROOT / "examples" / "ctcp_bridge_proposals" / "project_generation_bridge.proposal.json"
DEFAULT_PATCH_MANIFEST = ROOT / "examples" / "patch_manifests" / "project_generation_contract_bridge.patch_manifest.json"
DEFAULT_MIGRATION = ROOT / "examples" / "migrations" / "project_generation_next_steps.migration.json"
DEFAULT_FEATURE_MAP = ROOT / "examples" / "ctcp" / "ctcp_feature_map.json"
DEFAULT_SLICE_PROPOSAL = ROOT / "examples" / "proposals" / "replace_plan_provider_with_contract_only_ok.proposal.json"
FORBIDDEN_OUTPUT_NAMES = {"final_output", "project_output"}
FORBIDDEN_OUTPUT_SUFFIXES = {".db", ".sqlite", ".zip"}


def export_bridge_review_package(
    *,
    ctcp_root: pathlib.Path,
    output_dir: pathlib.Path,
    proposal_path: pathlib.Path = DEFAULT_PROPOSAL,
    patch_manifest_path: pathlib.Path = DEFAULT_PATCH_MANIFEST,
    migration_path: pathlib.Path = DEFAULT_MIGRATION,
    feature_map_path: pathlib.Path = DEFAULT_FEATURE_MAP,
    slice_proposal_path: pathlib.Path = DEFAULT_SLICE_PROPOSAL,
) -> dict[str, Any]:
    ctcp_root = ctcp_root.resolve()
    output_dir = output_dir.resolve()
    _validate_output_dir(ctcp_root, output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    copied = [
        _copy_artifact(proposal_path, output_dir),
        _copy_artifact(patch_manifest_path, output_dir),
        _copy_artifact(migration_path, output_dir),
    ]

    registry = ContractRegistry(ROOT, validate_schema=True)
    loader = SchemaLoader(ROOT)
    proposal = load_json(proposal_path)
    patch_manifest = load_json(patch_manifest_path)
    bridge_review = review_ctcp_bridge(proposal, patch_manifest, schema_loader=loader)
    chain_readiness = build_module_chain_readiness("all", ROOT)
    slice_readiness = check_slice_readiness(
        "feature.project_generation",
        load_json(feature_map_path),
        registry,
        ctcp_root,
        slice_proposal_path,
    )

    written = [
        *copied,
        _write_json(output_dir / "ctcp_bridge_review.json", bridge_review),
        _write_json(output_dir / "all_chain_readiness.json", chain_readiness),
        _write_json(output_dir / "slice_readiness.project_generation.json", slice_readiness),
    ]
    written.append(_write_summary(output_dir / "REVIEW_SUMMARY.md", proposal, bridge_review, chain_readiness, slice_readiness))
    _assert_no_forbidden_outputs(output_dir)
    return {
        "kind": "CTCPBridgeReviewPackageExport",
        "ok": bridge_review["ok"] and chain_readiness["ok"] and slice_readiness["ok"],
        "output_dir": str(output_dir),
        "written_files": [path.name for path in written],
        "bridge_review_status": bridge_review["approval_status"],
        "chain_readiness_status": chain_readiness["readiness_status"],
        "slice_readiness_status": slice_readiness["readiness_status"],
    }


def _validate_output_dir(ctcp_root: pathlib.Path, output_dir: pathlib.Path) -> None:
    if output_dir == ctcp_root or ctcp_root in output_dir.parents:
        raise ValueError("output_dir must not be inside the read-only CTCP checkout")
    parts = {part.lower() for part in output_dir.parts}
    if parts & FORBIDDEN_OUTPUT_NAMES or output_dir.suffix.lower() in FORBIDDEN_OUTPUT_SUFFIXES:
        raise ValueError("output_dir must not target DB, zip, final_output, or project_output paths")


def _copy_artifact(source: pathlib.Path, output_dir: pathlib.Path) -> pathlib.Path:
    target = output_dir / source.name
    shutil.copyfile(source, target)
    return target


def _write_json(path: pathlib.Path, value: dict[str, Any]) -> pathlib.Path:
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def _write_summary(
    path: pathlib.Path,
    proposal: dict[str, Any],
    bridge_review: dict[str, Any],
    chain_readiness: dict[str, Any],
    slice_readiness: dict[str, Any],
) -> pathlib.Path:
    risk_summary = bridge_review.get("risk_summary", {})
    proposed_files = "\n".join(f"- `{item}`" for item in bridge_review.get("proposed_files", [])) or "- None"
    entrypoints = "\n".join(f"- {item}" for item in bridge_review.get("preserved_entrypoints", [])) or "- None"
    required_tests = "\n".join(f"- {item}" for item in bridge_review.get("required_tests", [])) or "- None"
    risks = "\n".join(f"- `{key}`: `{value}`" for key, value in sorted(risk_summary.items())) or "- None"
    text = f"""# CTCP Bridge Review Package

Approval status: `{bridge_review.get("approval_status")}`

Target feature: `{bridge_review.get("target_feature")}`

Module chain readiness: `{chain_readiness.get("readiness_status")}`

Slice readiness: `{slice_readiness.get("readiness_status")}`

## Proposed Files
{proposed_files}

## Preserved Entrypoints
{entrypoints}

## Risks
{risks}

## Required Tests
{required_tests}

## Rollback Plan
{proposal.get("rollback_plan", "")}

## Safety Statement
CTCP was not modified by this export. The package is a CGNK-side review artifact only; no patches were applied, no providers were called, and no DB, zip, final_output, or project_output artifacts were created.
"""
    path.write_text(text, encoding="utf-8")
    return path


def _assert_no_forbidden_outputs(output_dir: pathlib.Path) -> None:
    for path in output_dir.rglob("*"):
        lowered_parts = {part.lower() for part in path.parts}
        if lowered_parts & FORBIDDEN_OUTPUT_NAMES or path.suffix.lower() in FORBIDDEN_OUTPUT_SUFFIXES:
            raise ValueError(f"forbidden generated output path: {path}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ctcp-root", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--proposal", default=str(DEFAULT_PROPOSAL))
    parser.add_argument("--patch-manifest", default=str(DEFAULT_PATCH_MANIFEST))
    parser.add_argument("--migration", default=str(DEFAULT_MIGRATION))
    args = parser.parse_args()

    result = export_bridge_review_package(
        ctcp_root=pathlib.Path(args.ctcp_root),
        output_dir=pathlib.Path(args.output_dir),
        proposal_path=pathlib.Path(args.proposal),
        patch_manifest_path=pathlib.Path(args.patch_manifest),
        migration_path=pathlib.Path(args.migration),
    )
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
