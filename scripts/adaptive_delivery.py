#!/usr/bin/env python3
from __future__ import annotations

import json
import pathlib
import re
from typing import Any, Callable


VERDICTS = {
    "PASS_FINAL",
    "DELIVER_WITH_WARNINGS",
    "NEEDS_REWORK",
    "ASK_USER_REVIEW",
    "FACT_BLOCKED",
}
DELIVERY_ALLOWED_VERDICTS = {"PASS_FINAL", "DELIVER_WITH_WARNINGS", "ASK_USER_REVIEW"}
FINAL_VERDICTS = {"PASS_FINAL", "DELIVER_WITH_WARNINGS"}
JUDGMENT_KEYS = {
    "verdict",
    "delivery_allowed",
    "is_final",
    "confidence",
    "reasons",
    "user_visible_warnings",
    "required_repairs",
    "can_send_artifacts",
    "must_not_claim",
}
PLACEHOLDER_MARKERS = (
    "placeholder",
    "mock",
    "fallback",
    "dummy",
    "sample_preview",
    "summary_preview",
    "delivery_summary",
    "占位",
    "模拟截图",
    "示例预览",
)
SOURCE_PLACEHOLDER_MARKERS = (
    "raise notimplementederror",
    "todo: implement",
    "placeholder implementation",
    "not implemented yet",
)
DEFAULT_ENTRYPOINTS = ("main.py", "app.py", "package.json", "index.html")
DEFAULT_PUBLIC_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".mp4", ".webm", ".zip"}
FINAL_PACKAGE_NAME = "final_project_bundle.zip"


def _text(path: pathlib.Path, limit: int = 16000) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")[:limit]
    except OSError:
        return ""


def _is_within(root: pathlib.Path, path: pathlib.Path) -> bool:
    try:
        resolved = path.resolve()
        root = root.resolve()
    except OSError:
        return False
    return resolved == root or root in resolved.parents


def _is_within_any(roots: list[pathlib.Path], path: pathlib.Path) -> bool:
    return any(_is_within(root, path) for root in roots)


def _iter_path_values(value: Any) -> list[str]:
    if isinstance(value, dict):
        out: list[str] = []
        for item in value.values():
            out.extend(_iter_path_values(item))
        return out
    if isinstance(value, list):
        out: list[str] = []
        for item in value:
            out.extend(_iter_path_values(item))
        return out
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def allowed_delivery_roots(project: pathlib.Path, manifest: dict[str, Any] | None = None) -> list[pathlib.Path]:
    manifest = manifest if isinstance(manifest, dict) else {}
    artifacts = manifest.get("artifacts", {}) if isinstance(manifest.get("artifacts"), dict) else {}
    roots: list[pathlib.Path] = [project.resolve()]
    for key in (
        "output_dir",
        "packager_output_dir",
        "delivery_dir",
        "run_dir",
        "runtime_dir",
        "artifact_dir",
        "artifacts_dir",
        "delivery_output_dir",
    ):
        for raw in _iter_path_values(manifest.get(key)):
            try:
                path = pathlib.Path(raw)
                if not path.is_absolute():
                    path = project / path
                roots.append(path.resolve())
            except OSError:
                continue
    for raw in _iter_path_values(manifest.get("manifest_path")):
        try:
            path = pathlib.Path(raw)
            if not path.is_absolute():
                path = project / path
            roots.append(path.resolve().parent)
        except OSError:
            continue
    for raw in _iter_path_values(manifest.get("package_path")) + _iter_path_values(artifacts.get("delivery_zip")):
        try:
            path = pathlib.Path(raw)
            if not path.is_absolute():
                path = project / path
            roots.append(path.resolve().parent)
        except OSError:
            continue
    deduped: list[pathlib.Path] = []
    seen: set[str] = set()
    for root in roots:
        key = str(root).lower()
        if key not in seen:
            seen.add(key)
            deduped.append(root)
    return deduped


def _resolve_claim(project: pathlib.Path, raw: Any, roots: list[pathlib.Path]) -> tuple[pathlib.Path | None, str]:
    value = str(raw or "").strip()
    if not value:
        return None, ""
    path = pathlib.Path(value)
    if not path.is_absolute():
        path = project / path
    try:
        resolved = path.resolve()
    except OSError:
        return None, "invalid_path"
    if not _is_within_any(roots, resolved):
        return resolved, "unsafe_path"
    return resolved, ""


def _placeholder(path: pathlib.Path) -> bool:
    lowered = path.name.lower()
    if any(marker in lowered for marker in PLACEHOLDER_MARKERS):
        return True
    if path.suffix.lower() in {".md", ".txt", ".html", ".svg", ".py", ".js", ".ts", ".tsx", ".jsx"}:
        content = _text(path).lower()
        return any(marker in content for marker in PLACEHOLDER_MARKERS)
    return False


def _placeholder_entrypoint(path: pathlib.Path | None) -> bool:
    if path is None or not path.is_file():
        return False
    lowered = _text(path).lower()
    compact = re.sub(r"\s+", " ", lowered)
    return _placeholder(path) or any(marker in compact for marker in SOURCE_PLACEHOLDER_MARKERS)


def _artifact_kind(path: pathlib.Path) -> str:
    lowered = str(path).replace("\\", "/").lower()
    suffix = path.suffix.lower()
    if suffix == ".zip":
        return "package"
    if suffix in {".mp4", ".webm", ".gif"}:
        return "video"
    if any(token in lowered for token in ("screenshot", "screen", "/ui", "interface", "界面", "截图")):
        return "screenshot"
    if any(token in lowered for token in ("background", "/bg", "scene", "背景")):
        return "background"
    if any(token in lowered for token in ("sprite", "character", "portrait", "立绘", "角色")):
        return "sprite"
    return "generated_image"


def _manifest_package_claims(manifest: dict[str, Any] | None = None, project_dir: str | pathlib.Path | None = None) -> set[str]:
    manifest = manifest if isinstance(manifest, dict) else {}
    artifacts = manifest.get("artifacts", {}) if isinstance(manifest.get("artifacts"), dict) else {}
    project = pathlib.Path(project_dir).resolve() if project_dir is not None else None
    claims: set[str] = set()
    for raw in _iter_path_values(manifest.get("package_path")) + _iter_path_values(artifacts.get("delivery_zip")):
        try:
            path = pathlib.Path(raw)
            if project is not None and not path.is_absolute():
                path = project / path
            claims.add(str(path.resolve()).lower())
        except OSError:
            continue
    return claims


def is_final_delivery_package(
    path: str | pathlib.Path,
    manifest: dict[str, Any] | None,
    project_dir: str | pathlib.Path,
    allowed_delivery_roots: list[pathlib.Path] | None = None,
) -> bool:
    candidate = pathlib.Path(path)
    try:
        resolved = candidate.resolve()
    except OSError:
        return False
    if resolved.suffix.lower() != ".zip" or resolved.name != FINAL_PACKAGE_NAME:
        return False
    roots = allowed_delivery_roots or allowed_delivery_roots_for(project_dir, manifest)
    if not _is_within_any(roots, resolved):
        return False
    project = pathlib.Path(project_dir).resolve()
    claimed = str(resolved).lower() in _manifest_package_claims(manifest, project)
    if claimed:
        return True
    return resolved.parent == project or resolved.parent in [root.resolve() for root in roots if root.resolve() != project]


def allowed_delivery_roots_for(project_dir: str | pathlib.Path, manifest: dict[str, Any] | None = None) -> list[pathlib.Path]:
    return allowed_delivery_roots(pathlib.Path(project_dir).resolve(), manifest)


def classify_delivery_artifact(
    path: str | pathlib.Path,
    manifest: dict[str, Any] | None,
    project_dir: str | pathlib.Path,
    *,
    allowed_roots: list[pathlib.Path] | None = None,
    public_suffixes: set[str] | None = None,
) -> dict[str, Any]:
    project = pathlib.Path(project_dir).resolve()
    candidate = pathlib.Path(path)
    suffixes = set(public_suffixes or DEFAULT_PUBLIC_SUFFIXES)
    try:
        resolved = candidate.resolve()
    except OSError:
        return {"path": str(candidate), "kind": "", "safe": False, "placeholder": False, "reason": "invalid_path"}
    roots = allowed_roots or allowed_delivery_roots(project, manifest)
    if not _is_within_any(roots, resolved):
        return {"path": str(resolved), "kind": "", "safe": False, "placeholder": False, "reason": "unsafe_path"}
    if not resolved.is_file():
        return {"path": str(resolved), "kind": "", "safe": False, "placeholder": False, "reason": "missing"}
    if resolved.suffix.lower() not in suffixes:
        return {"path": str(resolved), "kind": "", "safe": False, "placeholder": False, "reason": "not_public_suffix"}
    if resolved.suffix.lower() == ".zip" and not is_final_delivery_package(resolved, manifest, project, roots):
        return {"path": str(resolved), "kind": "zip", "safe": False, "placeholder": False, "reason": "non_final_zip"}
    placeholder = _placeholder(resolved)
    kind = _artifact_kind(resolved)
    return {
        "path": str(resolved),
        "kind": kind,
        "safe": not placeholder,
        "placeholder": placeholder,
        "reason": "placeholder" if placeholder else "ok",
    }


def collect_safe_delivery_artifacts(
    project_dir: str | pathlib.Path,
    manifest: dict[str, Any] | None = None,
    *,
    evidence: dict[str, Any] | None = None,
    public_suffixes: set[str] | None = None,
) -> list[dict[str, str]]:
    facts = delivery_fact_check(project_dir, manifest, evidence=evidence, phase="checkpoint", public_suffixes=public_suffixes)
    return [dict(item) for item in facts.get("safe_artifacts", []) if isinstance(item, dict)]


def _list_values(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def _provider_status(provider_result: dict[str, Any] | None) -> tuple[bool | None, str]:
    if not isinstance(provider_result, dict) or not provider_result:
        return None, "unknown"
    status = str(provider_result.get("status", "")).strip().lower()
    if status in {"pass", "passed", "ready", "success", "completed"}:
        return True, status
    return False, status or "missing"


def delivery_fact_check(
    project_dir: str | pathlib.Path,
    manifest: dict[str, Any] | None = None,
    *,
    evidence: dict[str, Any] | None = None,
    provider_result: dict[str, Any] | None = None,
    phase: str = "final",
    public_suffixes: set[str] | None = None,
    entrypoints: tuple[str, ...] = DEFAULT_ENTRYPOINTS,
) -> dict[str, Any]:
    project = pathlib.Path(project_dir).resolve()
    manifest = manifest if isinstance(manifest, dict) else {}
    evidence = evidence if isinstance(evidence, dict) else {}
    suffixes = set(public_suffixes or DEFAULT_PUBLIC_SUFFIXES)
    missing: list[str] = []
    warnings: list[str] = []
    hard_blockers: list[str] = []
    unsafe_paths: list[str] = []
    missing_claimed_artifacts: list[str] = []
    placeholder_artifacts: list[str] = []
    safe_artifacts: list[dict[str, str]] = []
    non_final_zips: list[str] = []
    any_zip_found = False
    roots = allowed_delivery_roots(project, manifest)

    project_exists = project.is_dir()
    readme = project / "README.md"
    test_plan = project / "TEST_PLAN.md"
    entrypoint = next((project / name for name in entrypoints if (project / name).is_file()), None) if project_exists else None
    entrypoint_placeholder = _placeholder_entrypoint(entrypoint)
    non_doc_files = []
    if project_exists:
        non_doc_files = [
            path
            for path in project.rglob("*")
            if path.is_file() and path.suffix.lower() not in {".md", ".txt", ".json", ".jsonl", ".log", ".yaml", ".yml"}
        ]
    real_generation_result = bool(project_exists and entrypoint and not entrypoint_placeholder and non_doc_files)

    if not project_exists:
        missing.append("project_dir")
        hard_blockers.append("project_dir_missing")
    if not readme.is_file():
        missing.append("README.md")
        warnings.append("README.md is missing")
    if not test_plan.is_file():
        missing.append("TEST_PLAN.md")
        warnings.append("TEST_PLAN.md is missing")
    if entrypoint is None:
        missing.append("entrypoint")
        hard_blockers.append("real_generation_result_missing")
    elif entrypoint_placeholder:
        hard_blockers.append("entrypoint_is_placeholder")
    if not real_generation_result and project_exists and "real_generation_result_missing" not in hard_blockers:
        hard_blockers.append("real_generation_result_missing")

    artifacts = manifest.get("artifacts", {}) if isinstance(manifest.get("artifacts"), dict) else {}
    claims: list[tuple[str, str]] = []
    for raw in _list_values(manifest.get("package_path")) + _list_values(artifacts.get("delivery_zip")):
        claims.append(("package", raw))
    for raw in _list_values(artifacts.get("preview_evidence")):
        claims.append(("preview", raw))
    for key in ("screenshots", "generated_images", "backgrounds", "characters", "sprites", "videos", "preview_files"):
        for raw in _list_values(evidence.get(key)):
            claims.append((key, raw))

    seen: set[str] = set()
    for claimed_kind, raw in claims:
        path, error = _resolve_claim(project, raw, roots)
        if error == "unsafe_path":
            unsafe_paths.append(str(path))
            continue
        if error or path is None:
            missing_claimed_artifacts.append(raw)
            continue
        key = str(path).lower()
        if key in seen:
            continue
        seen.add(key)
        if not path.is_file():
            missing_claimed_artifacts.append(str(path))
            continue
        if path.suffix.lower() == ".zip":
            any_zip_found = True
        classified = classify_delivery_artifact(path, manifest, project, allowed_roots=roots, public_suffixes=suffixes)
        reason = str(classified.get("reason", ""))
        if reason == "not_public_suffix":
            warnings.append(f"attachment is not publicly sendable: {path.name}")
            continue
        if reason == "non_final_zip":
            non_final_zips.append(str(path))
            if claimed_kind == "package":
                warnings.append(f"claimed zip is not a final delivery package: {path.name}")
            continue
        if classified.get("placeholder"):
            placeholder_artifacts.append(str(path))
            continue
        if not classified.get("safe"):
            continue
        safe_artifacts.append({"path": str(path), "kind": str(classified.get("kind", "")), "source": claimed_kind})

    if project_exists:
        for path in sorted(project.rglob("*")):
            if not path.is_file() or path.suffix.lower() not in suffixes:
                continue
            key = str(path.resolve()).lower()
            if key in seen:
                continue
            seen.add(key)
            if path.suffix.lower() == ".zip":
                any_zip_found = True
            classified = classify_delivery_artifact(path, manifest, project, allowed_roots=roots, public_suffixes=suffixes)
            reason = str(classified.get("reason", ""))
            if reason == "non_final_zip":
                non_final_zips.append(str(path.resolve()))
                continue
            if classified.get("placeholder"):
                placeholder_artifacts.append(str(path.resolve()))
                continue
            if classified.get("safe"):
                safe_artifacts.append({"path": str(path.resolve()), "kind": str(classified.get("kind", "")), "source": "project_scan"})

    if unsafe_paths:
        hard_blockers.append("unsafe_attachment_path")
    if missing_claimed_artifacts:
        hard_blockers.append("claimed_attachment_missing")
    if placeholder_artifacts:
        warnings.append("placeholder/mock/fallback artifacts were excluded from real evidence")
    if non_final_zips:
        warnings.append("non-delivery zip files were ignored as final packages")

    provider_success, provider_status = _provider_status(provider_result)
    if provider_success is False:
        hard_blockers.append("provider_not_successful")
    elif provider_success is None:
        warnings.append("provider success was not explicitly recorded")

    packages = [item for item in safe_artifacts if item["kind"] == "package"]
    previews = [item for item in safe_artifacts if item["kind"] != "package"]
    if phase == "final" and not packages:
        missing.append("delivery_zip")
        warnings.append("final delivery zip is missing")
    if not previews:
        missing.append("preview_evidence")
        warnings.append("preview evidence is missing")

    return {
        "kind": "CGNKDeliveryFactCheck",
        "phase": phase,
        "facts": {
            "project_dir_exists": project_exists,
            "readme_exists": readme.is_file(),
            "test_plan_exists": test_plan.is_file(),
            "entrypoint_exists": entrypoint is not None,
            "entrypoint_path": str(entrypoint.resolve()) if entrypoint else "",
            "entrypoint_is_placeholder": entrypoint_placeholder,
            "real_generation_result": real_generation_result,
            "any_zip_found": any_zip_found,
            "final_package_exists": bool(packages),
            "zip_exists": bool(packages),
            "preview_exists": bool(previews),
            "provider_success": provider_success,
            "provider_status": provider_status,
            "delivery_attachments_exist": not missing_claimed_artifacts,
            "paths_safe": not unsafe_paths,
        },
        "missing": sorted(set(missing)),
        "warnings": sorted(set(warnings)),
        "hard_blockers": sorted(set(hard_blockers)),
        "safe_artifacts": safe_artifacts,
        "placeholder_artifacts": sorted(set(placeholder_artifacts)),
        "non_final_zips": sorted(set(non_final_zips)),
        "missing_claimed_artifacts": sorted(set(missing_claimed_artifacts)),
        "unsafe_paths": sorted(set(unsafe_paths)),
        "allowed_delivery_roots": [str(root) for root in roots],
    }


def _review_failed(provider_result: dict[str, Any] | None) -> bool:
    if not isinstance(provider_result, dict):
        return False
    for key in ("provider_semantic_review", "review", "provider_review"):
        review = provider_result.get(key)
        if isinstance(review, dict) and str(review.get("status", "")).strip().lower() in {"fail", "failed", "rework"}:
            return True
    return False


def _test_warnings(test_report: Any, quality_evidence: dict[str, Any]) -> list[str]:
    warnings: list[str] = []
    text = ""
    if isinstance(test_report, dict):
        text = json.dumps(test_report, ensure_ascii=False)
    elif test_report:
        text = str(test_report)
    if not quality_evidence.get("test_report_found") and not text.strip():
        warnings.append("No complete test report is available.")
    if quality_evidence.get("test_report_has_no_test_executed"):
        warnings.append("The test report says no real test command was executed.")
    elif quality_evidence and not quality_evidence.get("test_report_has_commands"):
        warnings.append("The test report does not record reproducible commands.")
    return warnings


def _fallback_judgment(
    *,
    fact_check: dict[str, Any],
    quality_evidence: dict[str, Any],
    known_limits: list[str],
    test_report: Any,
    provider_result: dict[str, Any] | None,
    phase: str,
) -> dict[str, Any]:
    hard_blockers = list(fact_check.get("hard_blockers", []))
    warnings = list(fact_check.get("warnings", []))
    warnings.extend(_test_warnings(test_report, quality_evidence))
    warnings.extend(str(item) for item in known_limits if str(item).strip())
    warnings = list(dict.fromkeys(warnings))
    safe_paths = [str(item.get("path", "")) for item in fact_check.get("safe_artifacts", []) if item.get("path")]

    if hard_blockers:
        verdict = "FACT_BLOCKED"
        reasons = [f"Fact boundary failed: {item}" for item in hard_blockers]
        repairs = hard_blockers
    elif _review_failed(provider_result):
        verdict = "NEEDS_REWORK"
        reasons = ["The provider/review result explicitly requires rework."]
        repairs = ["Resolve the provider review issues before final delivery."]
    elif phase != "final" or not fact_check.get("facts", {}).get("final_package_exists"):
        verdict = "ASK_USER_REVIEW"
        reasons = ["The available real artifacts can be reviewed, but this is not a complete final delivery."]
        repairs = ["Create the final zip before claiming final delivery."] if phase == "final" else []
    elif warnings or fact_check.get("missing"):
        verdict = "DELIVER_WITH_WARNINGS"
        reasons = ["The real project artifacts are deliverable with explicit limitations."]
        repairs = []
    else:
        verdict = "PASS_FINAL"
        reasons = ["The final package and required factual artifacts exist."]
        repairs = []

    return {
        "verdict": verdict,
        "delivery_allowed": verdict in DELIVERY_ALLOWED_VERDICTS,
        "is_final": verdict in FINAL_VERDICTS,
        "confidence": 0.9 if verdict in {"FACT_BLOCKED", "PASS_FINAL"} else 0.75,
        "reasons": reasons,
        "user_visible_warnings": warnings,
        "required_repairs": repairs,
        "can_send_artifacts": safe_paths if verdict in DELIVERY_ALLOWED_VERDICTS else [],
        "must_not_claim": [
            "placeholder/mock/fallback artifacts as real screenshots, backgrounds, sprites, or generated evidence",
            *([f"excluded artifact: {path}" for path in fact_check.get("placeholder_artifacts", [])]),
        ],
    }


def _normalize_judgment(doc: dict[str, Any], fact_check: dict[str, Any], phase: str) -> dict[str, Any]:
    missing_keys = sorted(JUDGMENT_KEYS - set(doc))
    if missing_keys:
        raise ValueError("delivery judgment missing keys: " + ", ".join(missing_keys))
    verdict = str(doc.get("verdict", "")).strip().upper()
    if verdict not in VERDICTS:
        raise ValueError(f"invalid delivery verdict: {verdict!r}")
    try:
        confidence = max(0.0, min(1.0, float(doc.get("confidence", 0.0))))
    except (TypeError, ValueError):
        confidence = 0.0
    allowed_paths = {
        str(pathlib.Path(str(item.get("path", ""))).resolve())
        for item in fact_check.get("safe_artifacts", [])
        if str(item.get("path", "")).strip()
    }
    requested_paths = _list_values(doc.get("can_send_artifacts"))
    can_send = [str(pathlib.Path(path).resolve()) for path in requested_paths if str(pathlib.Path(path).resolve()) in allowed_paths]
    if not requested_paths and verdict in DELIVERY_ALLOWED_VERDICTS:
        can_send = sorted(allowed_paths)
    result = {
        "verdict": verdict,
        "delivery_allowed": bool(doc.get("delivery_allowed")) and verdict in DELIVERY_ALLOWED_VERDICTS,
        "is_final": bool(doc.get("is_final")) and verdict in FINAL_VERDICTS,
        "confidence": confidence,
        "reasons": _list_values(doc.get("reasons")),
        "user_visible_warnings": _list_values(doc.get("user_visible_warnings")),
        "required_repairs": _list_values(doc.get("required_repairs")),
        "can_send_artifacts": can_send,
        "must_not_claim": _list_values(doc.get("must_not_claim")),
    }
    hard_blockers = fact_check.get("hard_blockers", [])
    if hard_blockers:
        result.update(
            {
                "verdict": "FACT_BLOCKED",
                "delivery_allowed": False,
                "is_final": False,
                "can_send_artifacts": [],
                "required_repairs": list(dict.fromkeys(result["required_repairs"] + [str(item) for item in hard_blockers])),
            }
        )
    if phase == "final" and not fact_check.get("facts", {}).get("final_package_exists") and result["verdict"] == "PASS_FINAL":
        result.update({"verdict": "ASK_USER_REVIEW", "is_final": False})
    excluded = [str(item) for item in fact_check.get("placeholder_artifacts", [])]
    result["must_not_claim"] = list(
        dict.fromkeys(
            result["must_not_claim"]
            + ["placeholder/mock/fallback artifacts as real screenshots, backgrounds, sprites, or generated evidence"]
            + [f"excluded artifact: {path}" for path in excluded]
        )
    )
    return result


def agent_delivery_judgment(
    *,
    raw_user_goal: str,
    project_summary: str,
    delivery_fact_check: dict[str, Any],
    quality_evidence: dict[str, Any] | None = None,
    known_limits: list[str] | None = None,
    test_report: Any = None,
    preview_evidence: Any = None,
    provider_result: dict[str, Any] | None = None,
    phase: str = "final",
    agent: Callable[[list[dict[str, str]]], str | dict[str, Any]] | None = None,
) -> dict[str, Any]:
    quality = quality_evidence if isinstance(quality_evidence, dict) else {}
    limits = [str(item) for item in known_limits or [] if str(item).strip()]
    fallback = _fallback_judgment(
        fact_check=delivery_fact_check,
        quality_evidence=quality,
        known_limits=limits,
        test_report=test_report,
        provider_result=provider_result,
        phase=phase,
    )
    source = "local_agent_fallback"
    doc = fallback
    error = ""
    if callable(agent) and not delivery_fact_check.get("hard_blockers"):
        prompt = {
            "raw_user_goal": raw_user_goal,
            "project_summary": project_summary,
            "delivery_fact_check": delivery_fact_check,
            "quality_evidence": quality,
            "known_limits": limits,
            "test_report": test_report,
            "preview_evidence": preview_evidence,
            "provider_review_result": provider_result or {},
            "phase": phase,
        }
        messages = [
            {
                "role": "system",
                "content": (
                    "You are the CGNK adaptive delivery judge. Return one strict JSON object only. "
                    "Use verdict PASS_FINAL, DELIVER_WITH_WARNINGS, NEEDS_REWORK, ASK_USER_REVIEW, or FACT_BLOCKED. "
                    "Do not turn missing screenshots, incomplete tests, missing local models, or missing datasets into an automatic hard block. "
                    "Never claim placeholder/mock/fallback media as real evidence. FACT_BLOCKED is mandatory for unsafe paths, missing claimed attachments, "
                    "missing real project output, or explicit provider failure. PASS_FINAL requires a real final zip. "
                    "Required keys: verdict, delivery_allowed, is_final, confidence, reasons, user_visible_warnings, required_repairs, can_send_artifacts, must_not_claim."
                ),
            },
            {"role": "user", "content": json.dumps(prompt, ensure_ascii=False, indent=2)},
        ]
        try:
            raw = agent(messages)
            if isinstance(raw, dict):
                candidate = raw
            else:
                text = str(raw).strip()
                candidate = json.loads(text)
            if not isinstance(candidate, dict):
                raise ValueError("agent returned non-object")
            doc = candidate
            source = "provider_agent"
        except Exception as exc:
            error = str(exc)
            doc = fallback
    try:
        result = _normalize_judgment(doc, delivery_fact_check, phase)
    except Exception as exc:
        if not error:
            error = str(exc)
        source = "local_agent_fallback"
        result = _normalize_judgment(fallback, delivery_fact_check, phase)
    result["kind"] = "CGNKAgentDeliveryJudgment"
    result["judgment_source"] = source
    if error:
        result["agent_error"] = error
    result["delivery_fact_check"] = delivery_fact_check
    return result
