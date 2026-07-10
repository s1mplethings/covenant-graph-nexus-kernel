#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from typing import Any

try:
    import candidate_materializer  # noqa: F401
    import candidate_sanitizer  # noqa: F401
    import final_delivery_truth  # noqa: F401
    import post_build_finalize  # noqa: F401
    import post_build_repair  # noqa: F401
    import run_local_pipeline_impl as _impl
    import visual_evidence  # noqa: F401
except ModuleNotFoundError:  # pragma: no cover - package import path
    from scripts import candidate_materializer  # type: ignore[no-redef]  # noqa: F401
    from scripts import candidate_sanitizer  # type: ignore[no-redef]  # noqa: F401
    from scripts import final_delivery_truth  # type: ignore[no-redef]  # noqa: F401
    from scripts import post_build_finalize  # type: ignore[no-redef]  # noqa: F401
    from scripts import post_build_repair  # type: ignore[no-redef]  # noqa: F401
    from scripts import run_local_pipeline_impl as _impl  # type: ignore[no-redef]
    from scripts import visual_evidence  # type: ignore[no-redef]  # noqa: F401

# Thin compatibility orchestrator: public CLI and historical imports stay here;
# implementation details live in bounded pipeline modules and the compatibility backend.
globals().update({key: value for key, value in vars(_impl).items() if not key.startswith("_")})

ORCHESTRATION_MODULES = {
    "sanitize": candidate_sanitizer.run,
    "materialize": candidate_materializer.run,
    "post_build_finalize": post_build_finalize.run,
    "visual_evidence": visual_evidence.run,
    "final_delivery_truth": final_delivery_truth.run_if_applicable,
}

_PATCHABLE_IMPL_NAMES = [
    "compose_local_pipeline",
    "requirement_blueprint",
    "online_input_agent",
    "market_research_agent",
    "run_provider_semantic_review_with_repair",
    "provider_generate_project_by_components",
    "provider_generate_project_component",
    "provider_generate_project_component_split",
    "provider_component_file_manifest",
    "provider_generate_component_file",
    "provider_semantic_final_reducer",
    "provider_review_project",
    "provider_text",
    "make_example_outputs",
    "run_candidate_post_build_finalize",
    "capture_candidate_screenshot",
    "provider_post_build_file_repair",
]
_IMPL_ORIGINALS = {name: getattr(_impl, name) for name in _PATCHABLE_IMPL_NAMES if hasattr(_impl, name)}


def _sync_impl_from_public() -> None:
    public = globals()
    for name in _PATCHABLE_IMPL_NAMES:
        wrapper = globals().get(f"_wrapper_{name}")
        if name in public and public[name] is not wrapper:
            setattr(_impl, name, public[name])
        elif name in _IMPL_ORIGINALS:
            setattr(_impl, name, _IMPL_ORIGINALS[name])


def _wrapper_run_provider_semantic_review_with_repair(**kwargs: Any) -> dict[str, Any]:
    _sync_impl_from_public()
    return _impl.run_provider_semantic_review_with_repair(**kwargs)


def _wrapper_provider_generate_project_by_components(*args: Any, **kwargs: Any) -> dict[str, Any]:
    _sync_impl_from_public()
    return _impl.provider_generate_project_by_components(*args, **kwargs)


def _wrapper_provider_generate_project_component(*args: Any, **kwargs: Any) -> dict[str, Any]:
    _sync_impl_from_public()
    return _impl.provider_generate_project_component(*args, **kwargs)


def _wrapper_provider_generate_project_component_split(*args: Any, **kwargs: Any) -> dict[str, Any]:
    _sync_impl_from_public()
    return _impl.provider_generate_project_component_split(*args, **kwargs)


def _wrapper_provider_component_file_manifest(*args: Any, **kwargs: Any) -> list[dict[str, Any]]:
    _sync_impl_from_public()
    return _impl.provider_component_file_manifest(*args, **kwargs)


def _wrapper_provider_generate_component_file(*args: Any, **kwargs: Any) -> Any:
    _sync_impl_from_public()
    return _impl.provider_generate_component_file(*args, **kwargs)


def _wrapper_provider_semantic_final_reducer(*args: Any, **kwargs: Any) -> dict[str, Any]:
    _sync_impl_from_public()
    return _impl.provider_semantic_final_reducer(*args, **kwargs)


def _wrapper_provider_review_project(*args: Any, **kwargs: Any) -> dict[str, Any]:
    _sync_impl_from_public()
    return _impl.provider_review_project(*args, **kwargs)


def _wrapper_run_candidate_post_build_finalize(**kwargs: Any) -> dict[str, Any]:
    _sync_impl_from_public()
    result = _impl.run_candidate_post_build_finalize(**kwargs)
    project_dir = kwargs.get("project_dir")
    run_dir = kwargs.get("run_dir")
    if project_dir and run_dir:
        post_build_finalize.ensure_candidate_review_artifacts(project_dir, result)
        post_build_finalize.ensure_video_evidence(
            project_dir,
            run_dir,
            result,
            explicit_requested=kwargs.get("video_requested") if isinstance(kwargs.get("video_requested"), bool) else None,
            timeout=int(kwargs.get("timeout", 60) or 60),
        )
    return result


run_provider_semantic_review_with_repair = _wrapper_run_provider_semantic_review_with_repair
provider_generate_project_by_components = _wrapper_provider_generate_project_by_components
provider_generate_project_component = _wrapper_provider_generate_project_component
provider_generate_project_component_split = _wrapper_provider_generate_project_component_split
provider_component_file_manifest = _wrapper_provider_component_file_manifest
provider_generate_component_file = _wrapper_provider_generate_component_file
provider_semantic_final_reducer = _wrapper_provider_semantic_final_reducer
provider_review_project = _wrapper_provider_review_project
run_candidate_post_build_finalize = _wrapper_run_candidate_post_build_finalize
run_candidate_post_build_repair_loop = post_build_repair.run_candidate_post_build_repair_loop
capture_candidate_screenshot = visual_evidence.capture_candidate_screenshot
capture_candidate_video = visual_evidence.capture_candidate_video
video_file_diagnostics = visual_evidence.video_file_diagnostics
provider_post_build_file_repair = post_build_repair.provider_post_build_file_repair
compile_post_build_repair_plan = post_build_repair.compile_post_build_repair_plan
classify_post_build_failures = post_build_repair.classify_post_build_failures
apply_deterministic_post_build_repair = post_build_repair.apply_deterministic_post_build_repair


def execute(args: argparse.Namespace) -> dict[str, Any]:
    if getattr(args, "video", None) is False:
        os.environ["CGNK_DISABLE_VIDEO"] = "1"
    elif getattr(args, "video", None) is True:
        os.environ["CGNK_DISABLE_VIDEO"] = "0"
    _sync_impl_from_public()
    return _impl.execute(args)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.set_defaults(allow_network=False, allow_provider=False, use_api=False)
    parser.add_argument("--plan", default="")
    parser.add_argument("--goal", default="")
    parser.add_argument("--out-dir", default=str(_impl.DEFAULT_GENERATED_DIR))
    parser.add_argument("--run-dir", default=str(_impl.DEFAULT_RUN_DIR))
    parser.add_argument("--resume-run-dir", default="")
    parser.add_argument("--result", "--result-path", dest="result", default=str(_impl.DEFAULT_RESULT_PATH))
    parser.add_argument("--allow-network", dest="allow_network", action="store_true")
    parser.add_argument("--no-network", dest="allow_network", action="store_false")
    parser.add_argument("--allow-provider", dest="allow_provider", action="store_true")
    parser.add_argument("--no-provider", dest="allow_provider", action="store_false")
    parser.add_argument("--use-api", dest="use_api", action="store_true")
    parser.add_argument("--no-api", dest="use_api", action="store_false")
    parser.add_argument("--model", default="gpt-5.4-nano")
    parser.add_argument("--small-model", default="")
    parser.add_argument("--large-model", default="")
    parser.add_argument("--disable-model-routing", action="store_true")
    parser.add_argument("--video", dest="video", action="store_true", default=None)
    parser.add_argument("--no-video", dest="video", action="store_false")
    parser.add_argument("--timeout", type=int, default=360)
    parser.add_argument("--provider-semantic-repair-attempts", type=int, default=None)
    parser.add_argument("--post-build-repair-attempts", type=int, default=None)
    parser.add_argument("--allow-model-usage-planning", action="store_true", help="Opt in to model-planned usage validation; local deterministic planning is the default.")
    parser.add_argument("--phase-log-path", default="")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    result = execute(args)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"LOCAL_PIPELINE_EXECUTION: {result['status'].upper()}")
        print(f"project_dir={result['project_dir']}")
        print(f"run_dir={result['run_dir']}")
    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
