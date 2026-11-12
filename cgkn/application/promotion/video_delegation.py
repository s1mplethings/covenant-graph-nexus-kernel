"""Model-delegated Promotion Studio video improvement on the Host mainline.

The Planner is the existing ``AgentComposer``/``ProjectSession``; workers are
the existing ``LLMExecutor``; execution, state, recovery and acceptance remain
``DAGRunner``/``FileRunStore``/``GoalAcceptance``. This module only supplies the
video capability catalog, a deterministic plan consumer, and video-specific
checks. It does not create a second planner, scheduler, run store or acceptance
authority.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import time
from pathlib import Path
from typing import Any, Mapping

from cgkn.agent.catalog_composer import CatalogAgentComposer
from cgkn.agent.project_loop import ProjectSession
from cgkn.execution import BlockExecutionRequest, BlockExecutionResult, BlockStatus, ExecutionError, ExecutionErrorCode
from cgkn.execution.contracts import utc_now
from cgkn.execution.deliverables import FileDeliverableChecker
from cgkn.executors import ExecutorRegistry, LLMExecutor
from cgkn.orchestration.capability_tree import CapabilityTree, CapabilityNode
from cgkn.orchestration.leaf_contract import build_leaf_contract
from cgkn.providers import CGKNModelRouting, CompletionClient, ModelRoleConfig
from cgkn.runtime import DAGRunner
from cgkn.state import FileRunStore
from cgkn.runtime.acceptance import open_goal_acceptance as GoalAcceptance
from cgkn.state.acceptance import identity

from . import video_qab as q
from .video_contracts import (PUBLISH_EFFECTS, PUBLISH_EFFECTS_SCHEMA,
                              ExternalEffectBlocked, PreflightRejected,
                              PreflightedDAGRunner, validate_publish_effects)


SCENE_ORDER = ("intro", "projects", "content", "publish", "recording", "qab", "closing")
TECHNICAL_CONDITION = (
    "The final video passes independent deterministic checks for decode, duration, "
    "resolution, audio stream, real-GUI content and encoded subtitle presence. "
    "Perceptual quality remains pending human review and is not claimed."
)
PERCEPTUAL_OBLIGATIONS = (
    "video.subtitle_content_correctness",
    "video.subtitle_readability",
    "video.subtitle_no_occlusion",
    "video.visual_quality",
    "video.audio_intelligibility",
)
PLAN_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["schema_version", "strategy", "review_refs", "scenes", "subtitle", "effects"],
    "properties": {
        "schema_version": {"const": "1.0"},
        "strategy": {"type": "string", "minLength": 20},
        "review_refs": {"type": "array", "minItems": 2, "uniqueItems": True,
                        "items": {"enum": [f"V0{i}" for i in range(1, 9)]}},
        "scenes": {
            "type": "array", "minItems": 7, "maxItems": 7,
            "items": {
                "type": "object", "additionalProperties": False,
                "required": ["id", "source", "title", "kicker", "narration",
                             "on_screen", "focus", "highlight", "cards"],
                "properties": {
                    "id": {"enum": list(SCENE_ORDER)},
                    "source": {"type": ["string", "null"]},
                    "title": {"type": "string", "minLength": 1, "maxLength": 60},
                    "kicker": {"type": "string", "minLength": 1, "maxLength": 48},
                    "narration": {"type": "string", "minLength": 8, "maxLength": 140},
                    "on_screen": {"type": "string", "minLength": 1, "maxLength": 120},
                    "focus": {"type": ["object", "null"]},
                    "highlight": {"type": ["object", "null"]},
                    "cards": {"type": ["array", "null"], "maxItems": 8},
                },
            },
        },
        "subtitle": {
            "type": "object", "additionalProperties": False,
            "required": ["position", "margin_v", "font_size"],
            "properties": {
                "position": {"enum": ["bottom", "top"]},
                "margin_v": {"type": "integer", "minimum": 20, "maximum": 200},
                "font_size": {"type": "integer", "minimum": 12, "maximum": 24},
            },
        },
        "effects": PUBLISH_EFFECTS_SCHEMA,
    },
}
PLAN_INSTRUCTIONS = """You are the delegated video editor for one bounded improvement.
Read the external review and the frozen spec. Return a worker proposal whose single
write_file action writes trace/video_plan.json with exactly the plan_schema. The
plan must keep all seven scene ids in SCENE_ORDER, use only real GUI screenshot
names supplied in gui_screenshots, narrate in zh-CN, and make the intro scene open with a
real GUI screenshot that shows a recognizable product result in the first five seconds
(result-first opening: the intro must set source to a real screenshot, not null),
readable focus crops, and subtitles that do not cover the focus area. Do not claim
real social publishing. Do not change the spec, checkers, acceptance, or paths.
For image scenes use normalized focus/highlight boxes {x,y,w,h} between 0 and 1.
Every focus and highlight box must cover at least 0.15 on BOTH width and height,
and must stay inside the source frame (x+w <= 1, y+h <= 1).
The plan must include the top-level effects object exactly as defined by
plan_schema.properties.effects. Use target LOCAL_SIMULATED, side_effect_scope
LOCAL_ONLY, and false for external_network_post, external_account_mutation and
credential_use. Real social publishing is forbidden. Missing or different effect
values make the plan invalid; never omit effects and never assume local.
No HTML, no file paths outside trace/video_plan.json, no shell or network."""


def _sha(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _read_json(path: Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8")


def _result(request: BlockExecutionRequest, outputs: Mapping[str, Any],
            *, status: BlockStatus = BlockStatus.SUCCEEDED,
            error: ExecutionError | None = None, started: str = "",
            clock: float | None = None) -> BlockExecutionResult:
    return BlockExecutionResult(
        project_id=request.project_id, run_id=request.run_id,
        attempt_id=request.attempt_id, node_id=request.node_id,
        executor_ref=request.executor_ref, status=status, outputs=dict(outputs),
        error=error, started_at=started or utc_now(), ended_at=utc_now(),
        duration_ms=max(0, int((time.perf_counter() - (clock or time.perf_counter())) * 1000)),
    )


def _failed(request: BlockExecutionRequest, message: str, started: str,
            clock: float, code: ExecutionErrorCode = ExecutionErrorCode.INVALID_OUTPUT) -> BlockExecutionResult:
    return _result(request, {}, status=BlockStatus.FAILED,
                   error=ExecutionError(code, message), started=started, clock=clock)


class _HostExecutor:
    def __init__(self, capability: str, function, *, executor_ref: str | None = None):
        from cgkn.executors.protocol import ExecutorDescriptor
        self.capability = capability
        self.function = function
        ref = executor_ref or capability
        self.descriptor = ExecutorDescriptor(
            ref, "video_delegation", (capability,),
            ("filesystem.read", "filesystem.write"),
            default_timeout_seconds=900,
        )

    def execute(self, request: BlockExecutionRequest) -> BlockExecutionResult:
        from dataclasses import replace
        context = request.task_context
        short = _short_deps(dict(context.dependency_results))
        if short != dict(context.dependency_results):
            request = replace(request, task_context=replace(context, dependency_results=short))
        return self.function(request)


def _contract(node_id: str, goal: str, kind: str, scope: list[str],
              acceptance: list[str], checker: str, executor: str,
              dependencies: list[str], **details) -> dict:
    return build_leaf_contract(
        goal=goal, kind=kind, scope=scope, acceptance=acceptance,
        checker=checker, output_identity=node_id, effect_domains=["filesystem"],
        executor=executor, dependencies=dependencies, **details,
    )


def _node_config(capability: str, contract: dict, workdir: Path, run_id: str,
                 **extra: Any) -> dict:
    return {"executor_ref": capability, "workdir": str(workdir), "run_id": run_id,
            "leaf_contract": contract, **extra}


# ---------------------------------------------------------------------------
# Plan consumer: deterministic adapters that turn the model plan into the
# actual scene, slide, caption and mux inputs.
# ---------------------------------------------------------------------------

def _screenshot_map(gui: Mapping[str, Any]) -> dict[str, Path]:
    return {str(item["name"]): Path(item["path"]) for item in gui["screenshots"]}


def _validate_box(value: Any, label: str) -> dict[str, float] | None:
    if value is None:
        return None
    if not isinstance(value, Mapping) or set(value) != {"x", "y", "w", "h"}:
        raise ValueError(f"{label} must be null or an object with x,y,w,h")
    box = {key: float(value[key]) for key in ("x", "y", "w", "h")}
    if any(not 0.0 <= box[key] <= 1.0 for key in box):
        raise ValueError(f"{label} coordinates must be between 0 and 1")
    if box["w"] < 0.15 or box["h"] < 0.15:
        raise ValueError(f"{label} must cover at least 15% of each axis")
    if box["x"] + box["w"] > 1.0001 or box["y"] + box["h"] > 1.0001:
        raise ValueError(f"{label} exceeds the source frame")
    return box


def validate_plan(plan: Mapping[str, Any], gui: Mapping[str, Any],
                  spec: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(plan, Mapping) or plan.get("schema_version") != "1.0":
        raise ValueError("video plan has an unsupported schema")
    if "effects" not in plan:
        raise ValueError("PUBLISH_EFFECT_MISSING: effects object is required")
    if set(plan) != set(PLAN_SCHEMA["required"]):
        raise ValueError("video plan has missing or unknown top-level fields")
    strategy = plan.get("strategy")
    if not isinstance(strategy, str) or len(strategy.strip()) < 20:
        raise ValueError("video plan strategy is too short")
    refs = plan.get("review_refs")
    if not isinstance(refs, list) or len(refs) < 2 or not set(refs) <= {f"V0{i}" for i in range(1, 9)}:
        raise ValueError("video plan must cite at least two external review ids")
    validate_publish_effects(plan)
    scenes = plan.get("scenes")
    if not isinstance(scenes, list) or [item.get("id") for item in scenes] != list(SCENE_ORDER):
        raise ValueError("video plan must contain the seven scenes in fixed order")
    available = set(_screenshot_map(gui))
    used_sources: list[str] = []
    for scene in scenes:
        if not isinstance(scene, Mapping):
            raise ValueError("each scene must be an object")
        if set(scene) != set(PLAN_SCHEMA["properties"]["scenes"]["items"]["required"]):
            raise ValueError("scene has missing or unknown fields: " + str(scene.get("id")))
        narration = scene.get("narration")
        if not isinstance(narration, str) or not 8 <= len(narration.strip()) <= 140:
            raise ValueError("scene narration length is invalid: " + str(scene.get("id")))
        source = scene.get("source")
        if scene["id"] == "recording":
            if source is not None and source != "recording" and source not in available:
                raise ValueError("recording scene source must be null, recording, or a real screenshot")
        elif source is not None:
            if not isinstance(source, str) or source not in available:
                raise ValueError("scene must reference a real GUI screenshot: " + scene["id"])
            used_sources.append(source)
        _validate_box(scene.get("focus"), "focus")
        _validate_box(scene.get("highlight"), "highlight")
        cards = scene.get("cards")
        if cards is not None:
            if not isinstance(cards, list) or len(cards) > 8:
                raise ValueError("cards must be a bounded list")
            for card in cards:
                if not isinstance(card, list) or len(card) != 2 or not all(
                        isinstance(item, str) and item.strip() for item in card):
                    raise ValueError("each card must be a [label, value] string pair")
    if len(set(used_sources)) < 2:
        raise ValueError("plan must use at least two distinct real GUI screenshots")
    publish = next(item for item in scenes if item["id"] == "publish")
    subtitle = plan.get("subtitle")
    if not isinstance(subtitle, Mapping) or set(subtitle) != {"position", "margin_v", "font_size"}:
        raise ValueError("subtitle settings are invalid")
    if subtitle["position"] not in {"bottom", "top"}:
        raise ValueError("subtitle position is invalid")
    for key, low, high in (("margin_v", 20, 200), ("font_size", 12, 24)):
        if type(subtitle[key]) is not int or not low <= subtitle[key] <= high:
            raise ValueError("subtitle " + key + " is out of bounds")
    if not spec.get("subtitles", {}).get("required"):
        raise ValueError("plan requires the frozen subtitle spec")
    return dict(plan)


def _plan(workdir: Path) -> dict[str, Any]:
    return _read_json(workdir / "trace" / "video_plan.json")


def _dep(deps: Mapping[str, Any], name: str) -> Any:
    """Accept both the canonical node id (video.gui) and the legacy short key."""
    for key in (name, "video." + name):
        if key in deps:
            return deps[key]
    matches = [value for key, value in deps.items() if str(key).split(".")[-1] == name]
    if len(matches) == 1:
        return matches[0]
    raise KeyError(name)


def _short_deps(deps: Mapping[str, Any]) -> dict[str, Any]:
    merged = dict(deps)
    for key, value in deps.items():
        merged.setdefault(str(key).split(".")[-1], value)
    return merged



def _crop_screenshot(source: Path, box: Mapping[str, float] | None,
                     target: Path) -> Path:
    if box is None:
        return source
    import subprocess
    completed = subprocess.run(
        [str(q.FFPROBE), "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height", "-of", "json", str(source)],
        capture_output=True, text=True, check=True)
    stream = json.loads(completed.stdout)["streams"][0]
    width, height = int(stream["width"]), int(stream["height"])
    x = int(round(box["x"] * width)); y = int(round(box["y"] * height))
    w = max(2, int(round(box["w"] * width))); h = max(2, int(round(box["h"] * height)))
    target.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([str(q.FFMPEG), "-y", "-i", str(source),
                    "-vf", f"crop={w}:{h}:{x}:{y}", "-frames:v", "1", str(target)],
                   capture_output=True, check=True, timeout=120)
    return target


def _plan_slide_html(scene: Mapping[str, Any], image: Path | None,
                     highlight: Mapping[str, float] | None) -> str:
    body = ""
    if image is not None:
        body += f'<div class="frame"><img src="{q._data_uri(image)}" alt="real app screenshot">'
        if highlight:
            body += (f'<div class="focus" style="left:{highlight["x"]*100:.3f}%;'
                     f'top:{highlight["y"]*100:.3f}%;width:{highlight["w"]*100:.3f}%;'
                     f'height:{highlight["h"]*100:.3f}%"></div>')
        body += "</div>"
        if scene.get("on_screen"):
            body += f'<div class="sub" style="margin-top:16px">{scene["on_screen"]}</div>'
    elif scene.get("cards"):
        body += '<div class="grid">' + "".join(
            f'<div class="card"><b>{key}</b>{value}</div>' for key, value in scene["cards"]
        ) + "</div>"
        if scene.get("on_screen"):
            body += f'<div class="sub" style="margin-top:18px">{scene["on_screen"]}</div>'
    else:
        body += f'<div class="sub">{scene.get("on_screen", "")}</div>'
    extra = """
    .frame { position: relative; }
    .frame .focus { position: absolute; border: 4px solid #2dd4bf;
      box-shadow: 0 0 0 9999px rgba(4, 12, 20, 0.28); border-radius: 10px; }
    """
    return f"""<!doctype html><html lang="zh-CN"><meta charset="utf-8">
<style>{q.DESIGN_CSS}{extra}</style><body><div class="stage">
<div class="kicker">{scene["kicker"]}</div><h1>{scene["title"]}</h1>{body}
<div class="footer">PROMOTION STUDIO - LOCAL DEMO - MODEL-DELEGATED EDIT</div></div></body></html>"""


def exec_script_from_plan(request: BlockExecutionRequest) -> BlockExecutionResult:
    started, clock = request.created_at, time.perf_counter()
    try:
        cfg = dict(request.task_context.node_config)
        workdir = Path(cfg["workdir"])
        spec = q.ensure_spec(workdir)
        gui = dict(_dep(request.task_context.dependency_results, "gui")["gui"])
        plan = validate_plan(_plan(workdir), gui, spec)
        scenes = [{"scene": item["id"], "text": item["narration"].strip(),
                   "on_screen": item["on_screen"].strip()} for item in plan["scenes"]]
        _write_json(workdir / "trace" / "scenes.json", {"scenes": scenes})
        _write_json(workdir / "trace" / "narration_text.json", {
            "scenes": scenes, "language": "zh-CN",
            "plan_sha256": _sha(workdir / "trace" / "video_plan.json"),
            "strategy": plan["strategy"],
            "review_refs": plan["review_refs"],
        })
        return _result(request, {"scenes": scenes, "scene_count": len(scenes),
                                 "plan_sha256": _sha(workdir / "trace" / "video_plan.json")},
                       started=started, clock=clock)
    except Exception as exc:  # noqa: BLE001 - report exact consumer failure
        return _failed(request, f"PLAN_CONSUMPTION_FAILED: {exc}", started, clock)


def exec_design_from_plan(request: BlockExecutionRequest) -> BlockExecutionResult:
    started, clock = request.created_at, time.perf_counter()
    try:
        from playwright.sync_api import sync_playwright
        cfg = dict(request.task_context.node_config)
        workdir = Path(cfg["workdir"])
        spec = q.ensure_spec(workdir)
        gui = dict(_dep(request.task_context.dependency_results, "gui")["gui"])
        plan = validate_plan(_plan(workdir), gui, spec)
        screenshots = _screenshot_map(gui)
        design = workdir / "evidence" / "design"
        design.mkdir(parents=True, exist_ok=True)
        slides = []
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1920, "height": 1080})
            for index, scene in enumerate(plan["scenes"]):
                if scene["id"] == "recording":
                    continue  # the real recording is used directly by the render node
                slide_id = {
                    "intro": "00_intro", "projects": "01_projects",
                    "content": "02_content", "publish": "03_publish",
                    "qab": "04_qab", "closing": "05_closing",
                }[scene["id"]]
                name = slide_id
                image = None
                if scene["source"] in screenshots:
                    box = scene.get("focus")
                    cropped = design / (name + "_crop.png")
                    image = _crop_screenshot(screenshots[scene["source"]], box, cropped)
                html = _plan_slide_html(scene, image, scene.get("highlight"))
                html_path = design / (name + ".html")
                png_path = design / (name + ".png")
                html_path.write_text(html, encoding="utf-8")
                page.set_content(html, wait_until="load")
                page.wait_for_timeout(250)
                page.screenshot(path=str(png_path))
                slides.append({"id": name, "scene": scene["id"], "html": str(html_path),
                               "png": str(png_path), "sha256": _sha(png_path),
                               "source": scene["source"], "focus": scene.get("focus")})
            browser.close()
        storyboard = design / "storyboard.html"
        storyboard.write_text(
            "<!doctype html><meta charset=utf-8><title>Model-delegated storyboard</title>"
            "<body style='background:#0b1f2a;color:#f8fafc;font-family:Microsoft YaHei'>"
            + "".join(f"<section><h2>{s['scene']}</h2><img src='{Path(s['png']).name}' "
                      "style='width:960px'></section>" for s in slides)
            + "<h1>Promotion Studio - model-delegated edit</h1></body>",
            encoding="utf-8")
        manifest = {"slides": slides, "storyboard": str(storyboard),
                    "storyboard_sha256": _sha(storyboard),
                    "plan_sha256": _sha(workdir / "trace" / "video_plan.json")}
        _write_json(design / "design_manifest.json", manifest)
        manifest["design_manifest_sha256"] = _sha(design / "design_manifest.json")
        return _result(request, manifest, started=started, clock=clock)
    except Exception as exc:  # noqa: BLE001
        return _failed(request, f"PLAN_DESIGN_FAILED: {exc}", started, clock)


def exec_mux_from_plan(request: BlockExecutionRequest) -> BlockExecutionResult:
    started, clock = request.created_at, time.perf_counter()
    try:
        cfg = dict(request.task_context.node_config)
        workdir = Path(cfg["workdir"])
        deps = _short_deps(dict(request.task_context.dependency_results))
        plan = _plan(workdir)
        subtitle = plan.get("subtitle", {})
        overrides = {
            "Alignment": "2" if subtitle.get("position", "bottom") == "bottom" else "8",
            "MarginV": str(int(subtitle.get("margin_v", 48))),
            "FontSize": str(int(subtitle.get("font_size", 18))),
        }
        result = q.mux_final(workdir, Path(deps["render"]["draft"]),
                             Path(deps["tts"]["narration"]),
                             Path(deps["captions"]["srt"]),
                             workdir / "out" / "final.mp4",
                             style_overrides=overrides)
        result["srt_sha256"] = deps["captions"]["srt_sha256"]
        result["narration_sha256"] = deps["tts"]["narration_sha256"]
        result["subtitle_style"] = overrides
        result["plan_sha256"] = _sha(workdir / "trace" / "video_plan.json")
        return _result(request, result, started=started, clock=clock)
    except Exception as exc:  # noqa: BLE001
        return _failed(request, f"PLAN_MUX_FAILED: {exc}", started, clock)


def exec_qab_from_plan(request: BlockExecutionRequest,
                        acceptance: GoalAcceptance | None = None) -> BlockExecutionResult:
    started, clock = request.created_at, time.perf_counter()
    try:
        cfg = dict(request.task_context.node_config)
        workdir = Path(cfg["workdir"])
        spec = q.ensure_spec(workdir)
        deps = _short_deps(dict(request.task_context.dependency_results))
        final = Path(deps["mux"]["final"])
        design_manifest = _read_json(workdir / "evidence" / "design" / "design_manifest.json")
        technical = q.check_technical(workdir, final, spec)
        content = q.check_content(workdir, final, Path(deps["render"]["shot_manifest"]),
                                  design_manifest)
        subtitle = q.check_subtitles(workdir, final, Path(deps["captions"]["srt"]))
        audio = q.check_audio(workdir, Path(deps["tts"]["narration"]), spec)
        visual = q.check_visual(workdir, final)
        deterministic = {
            "technical": technical.get("status"),
            "content": content.get("status"),
            "subtitle": subtitle.get("status"),
            "audio": audio.get("status"),
        }
        passed = all(value == "PASS" for value in deterministic.values())
        final_hash = _sha(final)
        subjects = {"final.mp4": final_hash}
        if acceptance is not None:
            acceptance.bind_subjects(subjects)
        report = {
            "kind": "QABVideoDelegatedReport",
            "technical_status": "PASS" if passed else "FAIL",
            "overall_status": "PENDING_REVIEW" if passed else "FAIL",
            "perceptual_pending": list(PERCEPTUAL_OBLIGATIONS),
            "deterministic": deterministic,
            "technical": technical,
            "content": content,
            "subtitle": subtitle,
            "audio": audio,
            "visual": visual,
            "object_versions": {"final.mp4": final_hash},
            "plan_sha256": _sha(workdir / "trace" / "video_plan.json"),
        }
        _write_json(workdir / "trace" / "qab_report.json", report)
        _write_json(workdir / "evidence" / "results" / "qab.json", report)
        goal_check = {
            "goal_id": cfg.get("goal_id", "video.technical_delivery"),
            "condition_hash": identity(cfg["condition"]),
            "subjects": subjects,
            "execution": "VALID",
            "verdict": "VERIFIED" if passed else "FAILED",
            "observed": {
                "technical_status": "PASS" if passed else "FAIL",
                "deterministic": deterministic,
                "perceptual_pending": list(PERCEPTUAL_OBLIGATIONS),
                "final_sha256": final_hash,
            },
            "evidence_refs": [
                "evidence/results/technical.json",
                "evidence/results/content.json",
                "evidence/results/subtitle.json",
                "evidence/results/audio.json",
                "trace/qab_report.json",
            ],
            "checker_version": "1",
        }
        return _result(request, {"goal_check": goal_check, "report": report},
                       started=started, clock=clock)
    except Exception as exc:  # noqa: BLE001
        return _failed(request, f"QAB_CHECK_FAILED: {exc}", started, clock)


# ---------------------------------------------------------------------------
# Capability catalog and Host wiring
# ---------------------------------------------------------------------------

def build_video_catalog(workdir: Path, spec: Mapping[str, Any]) -> dict[str, Any]:
    workdir = Path(workdir)
    review_path = workdir / "VIDEO_REVIEW.md"
    if not review_path.is_file():
        raise FileNotFoundError("VIDEO_REVIEW.md is required in the run workspace")
    read_plan = {
        "video_task_spec.json": _sha(workdir / "video_task_spec.json"),
        "VIDEO_GOAL_RESOLUTION.md": _sha(workdir / "VIDEO_GOAL_RESOLUTION.md"),
        "VIDEO_REVIEW.md": _sha(review_path),
    }
    catalog: dict[str, Any] = {}
    catalog["video.spec@1"] = {
        "executor_ref": "promotion.video.spec@1",
        "config": _node_config("promotion.video.spec@1", _contract(
            "video.spec", "freeze the provisional video specification", "INSPECTION",
            ["video_task_spec.json", "VIDEO_GOAL_RESOLUTION.md"], ["video.spec.frozen"],
            "promotion.checker.spec@1", "promotion.video.spec@1", [],
            subject="video_task_spec.json", expected_observation="frozen spec present",
            pass_fail_rule="spec and goal resolution are readable"), workdir, "catalog"),
    }
    catalog["video.gui@1"] = {
        "executor_ref": "promotion.video.gui@1",
        "config": _node_config("promotion.video.gui@1", _contract(
            "video.gui", "capture the real Promotion Studio workflow", "IMPLEMENTATION",
            ["evidence/gui/01_projects.png", "evidence/gui/02_campaigns.png",
             "evidence/gui/03_content_draft.png", "evidence/gui/04_approved.png",
             "evidence/gui/05_published.png", "evidence/gui/06_receipts.png",
             "evidence/gui/gui_observations.json"],
            ["gui.key_pages"], "promotion.checker.gui@1", "promotion.video.gui@1", ["video.spec"],
            expected_delta="real screenshots and a real recording"), workdir, "catalog"),
    }
    catalog["video.gui_check@1"] = {
        "executor_ref": "promotion.video.gui-check@1",
        "config": _node_config("promotion.video.gui-check@1", _contract(
            "video.gui_check", "inspect real GUI labels and browser errors", "TEST",
            ["evidence/gui/gui_observations.json", "evidence/results/gui.json"],
            ["gui.key_pages"], "promotion.checker.gui@1", "promotion.video.gui-check@1",
            ["video.gui"], subject="gui_observations.json",
            expected_observation="key labels, no page errors, PUBLISHED receipt",
            pass_fail_rule="all key labels and receipt state present"), workdir, "catalog"),
    }
    catalog["video.plan@1"] = {
        "executor_ref": "llm.cheap@1",
        "config": _node_config("llm.cheap@1", _contract(
            "video.plan", "produce the model-delegated storyboard, narration and layout plan",
            "IMPLEMENTATION", ["trace/video_plan.json"], ["video.plan.consumed"],
            "promotion.checker.plan@1", "llm.cheap@1", ["video.spec", "video.gui"],
            expected_delta="one validated video_plan.json consumed downstream",
            read_subjects=read_plan, read_scope=sorted(read_plan),
            plan_schema=PLAN_SCHEMA, plan_instructions=PLAN_INSTRUCTIONS,
            gui_screenshots=["01_projects.png", "02_campaigns.png",
                             "03_content_draft.png", "04_approved.png",
                             "05_published.png", "06_receipts.png"]),
            workdir, "catalog"),
    }
    catalog["video.script@1"] = {
        "executor_ref": "promotion.video.script.plan@1",
        "config": _node_config("promotion.video.script.plan@1", _contract(
            "video.script", "consume the delegated plan as the scene and narration source",
            "IMPLEMENTATION", ["trace/scenes.json", "trace/narration_text.json"],
            ["video.script.plan"], "promotion.checker.script.plan@1",
            "promotion.video.script.plan@1", ["video.plan", "video.gui"],
            expected_delta="scenes and narration read from the model plan"), workdir, "catalog"),
    }
    catalog["video.design@1"] = {
        "executor_ref": "promotion.video.design.plan@1",
        "config": _node_config("promotion.video.design.plan@1", _contract(
            "video.design", "render real-GUI focus crops and text from the delegated plan",
            "IMPLEMENTATION",
            ["evidence/design/storyboard.html", "evidence/design/design_manifest.json"],
            ["html.storyboard_text"], "promotion.checker.design.plan@1",
            "promotion.video.design.plan@1", ["video.gui", "video.plan"],
            expected_delta="slides and storyboard driven by the model plan"), workdir, "catalog"),
    }
    catalog["video.tts@1"] = {
        "executor_ref": "promotion.video.tts@1",
        "config": _node_config("promotion.video.tts@1", _contract(
            "video.tts", "synthesize local Chinese narration from the delegated script",
            "IMPLEMENTATION", ["evidence/audio/narration.wav", "trace/tts_manifest.json"],
            ["video.audio_narration"], "promotion.checker.tts@1",
            "promotion.video.tts@1", ["video.script"],
            expected_delta="narration.wav and scene timings"), workdir, "catalog"),
    }
    catalog["video.captions@1"] = {
        "executor_ref": "promotion.video.captions@1",
        "config": _node_config("promotion.video.captions@1", _contract(
            "video.captions", "build subtitles from the delegated narration and timings",
            "IMPLEMENTATION", ["out/demo.srt", "trace/captions.json"],
            ["video.subtitle_presence"], "promotion.checker.captions@1",
            "promotion.video.captions@1", ["video.script", "video.tts"],
            expected_delta="SRT cues from the delegated narration"), workdir, "catalog"),
    }
    catalog["video.render@1"] = {
        "executor_ref": "promotion.video.render@1",
        "config": _node_config("promotion.video.render@1", _contract(
            "video.render", "render the real GUI slides and recording", "IMPLEMENTATION",
            ["out/draft_no_subs.mp4", "trace/shot_manifest.json"],
            ["video.render.complete"], "promotion.checker.render@1",
            "promotion.video.render@1", ["video.design", "video.tts", "video.gui"],
            expected_delta="draft video from current slides and narration"), workdir, "catalog"),
    }
    catalog["video.mux@1"] = {
        "executor_ref": "promotion.video.mux.plan@1",
        "config": _node_config("promotion.video.mux.plan@1", _contract(
            "video.mux", "mux the final video with the delegated subtitle placement",
            "IMPLEMENTATION", ["out/final.mp4"], ["video.final.mp4"],
            "promotion.checker.mux.plan@1", "promotion.video.mux.plan@1",
            ["video.render", "video.tts", "video.captions"],
            expected_delta="final encoded video with current audio and subtitles"),
            workdir, "catalog"),
    }
    catalog["video.qab@1"] = {
        "executor_ref": "promotion.video.qab@1",
        "config": _node_config("promotion.video.qab@1", _contract(
            "video.qab", "independently check the final video and record pending perception",
            "TEST", ["trace/qab_report.json", "evidence/results/qab.json"],
            ["video.technical_delivery"], "promotion.checker.qab.plan@1",
            "promotion.video.qab@1",
            ["video.mux", "video.render", "video.captions", "video.tts"],
            subject="final.mp4",
            expected_observation="deterministic checks pass; perception pending",
            pass_fail_rule="all deterministic checks PASS; perceptual items remain pending"),
            workdir, "catalog", condition=TECHNICAL_CONDITION,
            goal_id="video.technical_delivery"),
    }
    return catalog


def install_video_acceptance(store: FileRunStore, project_id: str, run_id: str,
                             final_name: str = "final.mp4") -> GoalAcceptance:
    acceptance = GoalAcceptance(
        store, project_id, run_id,
        {"R-technical": {"must": True}, "R-perceptual": {"must": False}},
        {"qab": "promotion.video.qab@1"},
    )
    acceptance.bind_subjects({final_name: "UNMATERIALIZED"})
    plan = {
        "phases": [{"id": "delivery", "depends_on": []}],
        "goals": [{
            "id": "video.technical_delivery",
            "phase_id": "delivery",
            "requirement_refs": ["R-technical"],
            "acceptance": TECHNICAL_CONDITION,
            "subject_refs": [final_name],
            "checker": "qab",
            "checker_version": "1",
            "task_refs": [],
        }],
    }
    acceptance.propose(plan, CapabilityTree("delegated video improvement", ()))
    acceptance.commit(plan)
    return acceptance


def register_video_executors(registry: ExecutorRegistry, workdir: Path,
                             run_id: str, client: CompletionClient,
                             worker_config: ModelRoleConfig,
                             acceptance: GoalAcceptance,
                             catalog: Mapping[str, Any]) -> dict[str, str]:
    workdir = Path(workdir)
    deterministic = {
        "promotion.video.spec@1": q.EXECUTORS["promotion.video.spec@1"],
        "promotion.video.gui@1": q.EXECUTORS["promotion.video.gui@1"],
        "promotion.video.gui-check@1": q.EXECUTORS["promotion.video.gui-check@1"],
        "promotion.video.script.plan@1": exec_script_from_plan,
        "promotion.video.design.plan@1": exec_design_from_plan,
        "promotion.video.tts@1": q.EXECUTORS["promotion.video.tts@1"],
        "promotion.video.captions@1": q.EXECUTORS["promotion.video.captions@1"],
        "promotion.video.render@1": q.EXECUTORS["promotion.video.render@1"],
        "promotion.video.mux.plan@1": exec_mux_from_plan,
        "promotion.video.qab@1": lambda request: exec_qab_from_plan(request, acceptance),
    }
    for cap, entry in catalog.items():
        ref = entry["executor_ref"]
        function = deterministic.get(ref)
        if function is None:
            continue
        registry.register(_HostExecutor(cap, function, executor_ref=ref))
    # The worker node reuses the existing LLMExecutor.
    llm = LLMExecutor(workdir, client, worker_config)
    registry.register(llm)
    checks: dict[str, Any] = {}
    for ref, entry in catalog.items():
        contract = entry["config"]["leaf_contract"]
        for name in contract.get("acceptance", ()):
            checks[str(name)] = q._generic_deliverable_check
    registry.register(FileDeliverableChecker(workdir, checks))
    return {entry["config"]["leaf_contract"]["checker_ref"]: "deliverable.files@1"
            for entry in catalog.values()}


def prepare_workspace(workdir: Path, spec_source: Path, goal_source: Path,
                      review_source: Path) -> dict[str, Any]:
    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    for source, target in ((spec_source, workdir / "video_task_spec.json"),
                           (goal_source, workdir / "VIDEO_GOAL_RESOLUTION.md"),
                           (review_source, workdir / "VIDEO_REVIEW.md")):
        source = Path(source)
        if not source.is_file():
            raise FileNotFoundError(str(source))
        if source.resolve() != target.resolve():
            shutil.copy2(source, target)
    spec = q.ensure_spec(workdir)
    return spec


def run_video_delegation(*, workdir: Path, project_id: str, run_id: str,
                         client: CompletionClient, routing: CGKNModelRouting,
                         spec_source: Path, goal_source: Path, review_source: Path,
                         max_decisions: int = 4) -> dict[str, Any]:
    workdir = Path(workdir)
    spec = prepare_workspace(workdir, spec_source, goal_source, review_source)
    catalog = build_video_catalog(workdir, spec)
    store = FileRunStore(workdir / "state")
    acceptance = install_video_acceptance(store, project_id, run_id)
    registry = ExecutorRegistry()
    deliverable = register_video_executors(registry, workdir, run_id, client,
                                           routing.worker, acceptance, catalog)
    runner = PreflightedDAGRunner(registry, store, max_parallel=1,
                                 deliverable_checkers=deliverable,
                                 catalog=catalog, workdir=workdir)
    composer = CatalogAgentComposer(client, routing.agent,
                                    require_decision_audit=False,
                                    allow_goal_plan=False,
                                    root_config={"acceptance_goal_id":
                                                 "video.technical_delivery"})
    goal = (
        "Improve only the opening product-demo segment of the current 55.53-second "
        "Promotion Studio local demo for a first-time viewer, using the supplied external "
        "review. The opening must show a recognizable product result within the first five "
        "seconds and then one real operation, state change and result, using real GUI "
        "captures only; keep the provisional 30-60 second, 1920x1080, 30fps, zh-CN "
        "specification; do not claim real social publishing. First compose and run the real GUI capture. "
        "Use the catalog output identity as the node_id (video.spec, video.gui, video.gui_check, "
        "video.plan, video.script, video.design, video.tts, video.captions, video.render, video.mux, "
        "video.qab); do not invent n_ prefixes, because dependency identities must match. "
        "Compose the complete chain needed for technical delivery in the first decision, then request a run. "
        "Then add a delegated video plan worker plus the deterministic consumers and "
        "independent QAB checker from the catalog. The worker must write a plan that "
        "the script, design, captions and mux nodes actually consume. If the plan is "
        "invalid or a deterministic check fails, make at most one bounded repair by "
        "updating the plan config and retrying the plan node. Finish only when the "
        "independent technical-delivery checker is verified. Perceptual quality stays "
        "pending human review."
    )
    session = ProjectSession(
        composer, runner, store, known_capabilities=set(catalog),
        worker_model=routing.worker.model, capability_catalog=catalog,
        max_decisions=max_decisions, acceptance=acceptance,
    )
    try:
        result = session.run(project_id=project_id, run_id=run_id, goal=goal,
                             constraints=("Use only real GUI captures",
                                          "Do not alter the frozen spec or checkers",
                                          "Do not claim real social publishing",
                                          "Perceptual review remains pending"))
    except PreflightRejected as exc:
        payload = {
            "kind": "DelegatedVideoImprovementResult",
            "project_id": project_id, "run_id": run_id,
            "status": "S0_RETRY_PRECHECK_FAIL",
            "decision_count": 0,
            "agent_calls": 0, "worker_calls": 0,
            "escalation_reason": "deterministic preflight rejected the tree before any worker dispatch",
            "preflight": exc.report,
            "workspace": str(workdir),
            "final_mp4": None, "final_sha256": None,
            "plan_path": str(workdir / "trace" / "video_plan.json"),
            "plan_sha256": None,
        }
        _write_json(workdir / "trace" / "delegation_result.json", payload)
        return payload
    payload = {
        "kind": "DelegatedVideoImprovementResult",
        "project_id": project_id, "run_id": run_id,
        "status": result.status, "decision_count": result.decision_count,
        "agent_calls": result.agent_calls, "worker_calls": result.worker_calls,
        "escalation_reason": result.escalation_reason,
        "run_summary": result.run_summary.as_dict() if result.run_summary else None,
        "tree": result.tree.as_dict(),
        "goal_acceptance": acceptance.view(),
        "workspace": str(workdir),
        "final_mp4": str(workdir / "out" / "final.mp4"),
        "final_sha256": _sha(workdir / "out" / "final.mp4") if (workdir / "out" / "final.mp4").is_file() else None,
        "plan_path": str(workdir / "trace" / "video_plan.json"),
        "plan_sha256": _sha(workdir / "trace" / "video_plan.json") if (workdir / "trace" / "video_plan.json").is_file() else None,
    }
    _write_json(workdir / "trace" / "delegation_result.json", payload)
    return payload


__all__ = [
    "PLAN_SCHEMA", "PLAN_INSTRUCTIONS", "TECHNICAL_CONDITION", "PERCEPTUAL_OBLIGATIONS",
    "build_video_catalog", "install_video_acceptance", "prepare_workspace",
    "run_video_delegation", "validate_plan", "exec_script_from_plan",
    "exec_design_from_plan", "exec_mux_from_plan", "exec_qab_from_plan",
]
