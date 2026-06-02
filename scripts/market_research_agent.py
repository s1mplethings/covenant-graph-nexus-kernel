#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Any


ROOT = pathlib.Path(__file__).resolve().parents[1]
GITHUB_SEARCH_API = "https://api.github.com/search/repositories"
NPM_SEARCH_API = "https://registry.npmjs.org/-/v1/search"
HUGGINGFACE_MODELS_API = "https://huggingface.co/api/models"
USER_AGENT = "CGNK-MarketResearchAgent/1.0"


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def request_json(url: str, timeout: int = 30) -> Any:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    last_error: Exception | None = None
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8", errors="replace"))
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError, json.JSONDecodeError) as exc:
            last_error = exc
            time.sleep(min(10.0, 1.5 * (attempt + 1)))
    raise RuntimeError(f"market research request failed: {last_error}")


def contains_any(text: str, terms: tuple[str, ...]) -> bool:
    lowered = str(text or "").lower()
    return any(term in lowered for term in terms)


def compact_tokens(text: str, limit: int = 8) -> list[str]:
    tokens = re.findall(r"[a-zA-Z][a-zA-Z0-9_+#.-]{2,}|[\u4e00-\u9fff]{2,}", str(text or "").lower())
    stop = {
        "project",
        "local",
        "tool",
        "assistant",
        "生成",
        "项目",
        "本地",
        "助手",
        "可以",
        "直接",
        "output",
        "input",
    }
    out: list[str] = []
    for token in tokens:
        if token not in stop and token not in out:
            out.append(token)
        if len(out) >= limit:
            break
    return out or ["software"]


def infer_domain_features(goal: str, blueprint: dict[str, Any]) -> list[dict[str, Any]]:
    text = str(goal or "")
    lowered = text.lower()
    features: list[dict[str, Any]] = []

    def add(feature_id: str, name: str, query: str, kind: str, rationale: str) -> None:
        if not any(row["id"] == feature_id for row in features):
            features.append({"id": feature_id, "name": name, "query": query, "kind": kind, "rationale": rationale})

    if contains_any(lowered, ("vn", "visual novel", "视觉小说")):
        add("market_vn_timeline", "VN story timeline and scene planning", "visual novel story timeline editor", "workflow", "The request needs story logic and timeline organization.")
    if contains_any(lowered, ("立绘", "character", "character art", "角色")):
        add("market_character_art", "AI character sprite generation", "AI character sprite generator visual novel", "ai_image", "The request asks for generated character art.")
    if contains_any(lowered, ("背景", "background", "scene art")):
        add("market_background_art", "AI background scene generation", "AI visual novel background generator", "ai_image", "The request asks for generated background art.")
    if contains_any(lowered, ("video", "mp4", "演示视频", "视频", "录屏")):
        add("market_demo_video", "Workflow demo video generation", "browser automation record demo video playwright ffmpeg", "automation", "The request expects a full process demo video.")
    if contains_any(lowered, ("web", "ui", "界面", "本地可运行", "local")):
        add("market_local_ui", "Local runnable UI", "local web app UI gradio streamlit flask", "ui", "The user wants to run and test the project locally.")
    if contains_any(lowered, ("高光", "highlight", "剪辑", "game video", "游戏视频")):
        add("market_video_highlight", "Game video highlight detection", "game video highlight detection ffmpeg opencv scene audio", "media_video", "The request asks for automated highlight clipping.")
    if contains_any(lowered, ("ocr", "票据", "发票", "文字识别")):
        add("market_ocr", "OCR document/image understanding", "OCR document extraction tesseract easyocr paddleocr", "vision", "The request needs text extraction from images or documents.")
    if contains_any(lowered, ("任务", "task", "todo", "kanban", "看板")):
        add("market_task_board", "Task board and status workflow", "task board todo kanban local web app", "workflow", "The request needs task creation and completion workflow.")
    if contains_any(lowered, ("新增任务", "add task", "create task", "完成任务", "complete task")):
        add("market_task_crud", "Task create/complete interactions", "todo app create complete task flask local storage", "ui", "The request explicitly needs adding and completing tasks.")
    if contains_any(lowered, ("本地保存", "持久化", "local storage", "tasks.json", "保存")):
        add("market_local_persistence", "Local persistence for project data", "local json persistence task app python flask", "general", "The request or workflow needs local state persistence.")

    blueprint_features = blueprint.get("feature_spec", {}).get("features", []) if isinstance(blueprint, dict) else []
    if not features:
        for row in blueprint_features[:6] if isinstance(blueprint_features, list) else []:
            name = str(row.get("name", "")).strip()
            desc = str(row.get("description", "")).strip()
            if name and name not in {"Project intake", "Requirement understanding", "Gap confirmation"}:
                add(f"blueprint_{row.get('id', len(features) + 1)}", name, " ".join(compact_tokens(name + " " + desc, 6)), "general", "Feature came from the requirement blueprint.")

    if not features:
        keywords = " ".join(compact_tokens(text, 6))
        add("market_general_solution", "General solution and comparable projects", keywords, "general", "Fallback research for a custom application request.")
    return features[:10]


def github_repositories(query: str, limit: int = 5) -> list[dict[str, Any]]:
    params = {"q": query, "sort": "stars", "order": "desc", "per_page": str(limit)}
    doc = request_json(GITHUB_SEARCH_API + "?" + urllib.parse.urlencode(params))
    items = doc.get("items", []) if isinstance(doc, dict) else []
    out: list[dict[str, Any]] = []
    for item in items[:limit] if isinstance(items, list) else []:
        if not isinstance(item, dict):
            continue
        out.append(
            {
                "source": "GitHub",
                "name": item.get("full_name", ""),
                "url": item.get("html_url", ""),
                "stars": item.get("stargazers_count", 0),
                "language": item.get("language", ""),
                "description": item.get("description", ""),
                "license": (item.get("license") or {}).get("spdx_id") if isinstance(item.get("license"), dict) else "",
            }
        )
    return out


def npm_packages(query: str, limit: int = 5) -> list[dict[str, Any]]:
    params = {"text": query, "size": str(limit)}
    doc = request_json(NPM_SEARCH_API + "?" + urllib.parse.urlencode(params))
    objects = doc.get("objects", []) if isinstance(doc, dict) else []
    out: list[dict[str, Any]] = []
    for obj in objects[:limit] if isinstance(objects, list) else []:
        package = obj.get("package", {}) if isinstance(obj, dict) else {}
        score = obj.get("score", {}) if isinstance(obj, dict) else {}
        if not isinstance(package, dict):
            continue
        out.append(
            {
                "source": "npm",
                "name": package.get("name", ""),
                "url": package.get("links", {}).get("npm", "") if isinstance(package.get("links"), dict) else "",
                "version": package.get("version", ""),
                "description": package.get("description", ""),
                "score": score.get("final") if isinstance(score, dict) else None,
            }
        )
    return out


def huggingface_models(query: str, kind: str, limit: int = 6) -> list[dict[str, Any]]:
    pipeline = "text-to-image" if kind == "ai_image" else ("video-classification" if kind == "media_video" else "")
    params = {"sort": "downloads", "direction": "-1", "limit": str(limit), "full": "true"}
    if pipeline:
        params["pipeline_tag"] = pipeline
    else:
        params["search"] = query
    doc = request_json(HUGGINGFACE_MODELS_API + "?" + urllib.parse.urlencode(params))
    items = doc if isinstance(doc, list) else []
    out: list[dict[str, Any]] = []
    for item in items[:limit]:
        if not isinstance(item, dict):
            continue
        model_id = str(item.get("modelId", "")).strip()
        if not model_id:
            continue
        tags = item.get("tags", [])
        out.append(
            {
                "source": "Hugging Face",
                "name": model_id,
                "url": f"https://huggingface.co/{model_id}",
                "pipeline_tag": item.get("pipeline_tag", pipeline),
                "downloads": item.get("downloads"),
                "likes": item.get("likes"),
                "tags": [str(tag) for tag in tags[:20]] if isinstance(tags, list) else [],
                "requires": "HF_TOKEN or a configured Hugging Face Inference Provider",
            }
        )
    return out


def static_provider_candidates(kind: str) -> list[dict[str, Any]]:
    if kind == "ai_image":
        return [
            {
                "source": "ProviderCatalog",
                "name": "OpenAI Images API / gpt-image-1",
                "url": "https://platform.openai.com/docs/guides/image-generation",
                "requires": "OPENAI_API_KEY and an Images-capable base URL",
                "fit": "High-quality prompt-to-image generation for generated backgrounds and sprites.",
            },
            {
                "source": "ProviderCatalog",
                "name": "Replicate FLUX / SDXL text-to-image",
                "url": "https://replicate.com/docs",
                "requires": "REPLICATE_API_TOKEN",
                "fit": "Good hosted model catalog when exact image model choice should be configurable.",
            },
        ]
    if kind == "automation":
        return [
            {
                "source": "ProviderCatalog",
                "name": "Playwright + ffmpeg",
                "url": "https://playwright.dev/",
                "requires": "Playwright browser runtime and ffmpeg",
                "fit": "Records actual UI workflows and converts browser video to MP4.",
            }
        ]
    if kind == "ui":
        return [
            {
                "source": "ProviderCatalog",
                "name": "Gradio",
                "url": "https://www.gradio.app/",
                "requires": "Python package gradio",
                "fit": "Fast local UI for ML/image generation workflows with galleries and examples.",
            },
            {
                "source": "ProviderCatalog",
                "name": "Streamlit",
                "url": "https://streamlit.io/",
                "requires": "Python package streamlit",
                "fit": "Local data/app UI with quick controls and previews.",
            },
            {
                "source": "ProviderCatalog",
                "name": "Flask/FastAPI + HTML",
                "url": "https://flask.palletsprojects.com/",
                "requires": "Python web framework",
                "fit": "More controllable local web app when custom UX and browser automation selectors matter.",
            },
        ]
    return []


def text_relevance(candidate: dict[str, Any], query: str) -> float:
    query_terms = set(compact_tokens(query, 10))
    haystack = " ".join(
        str(candidate.get(key, ""))
        for key in ("name", "description", "fit", "pipeline_tag")
    ).lower()
    if not query_terms:
        return 0.0
    hits = sum(1 for term in query_terms if term.lower() in haystack)
    return hits / max(1, len(query_terms))


def candidate_score(candidate: dict[str, Any], query: str, kind: str) -> float:
    source = str(candidate.get("source", ""))
    relevance = text_relevance(candidate, query)
    score = relevance * 40.0
    if source == "GitHub":
        score += min(float(candidate.get("stars") or 0) / 1000.0, 25.0)
    elif source == "Hugging Face":
        score += min(float(candidate.get("downloads") or 0) / 100000.0, 30.0)
        score += min(float(candidate.get("likes") or 0) / 500.0, 10.0)
    elif source == "npm":
        score += min(float(candidate.get("score") or 0) * 10.0, 20.0)
    elif source == "ProviderCatalog":
        score += 28.0
    if kind == "ai_image" and source in {"ProviderCatalog", "Hugging Face"}:
        score += 15.0
    if kind == "ui" and candidate.get("name") in {"Gradio", "Streamlit", "Flask/FastAPI + HTML"}:
        score += 15.0
    if relevance == 0 and source not in {"ProviderCatalog", "Hugging Face"}:
        score -= 25.0
    return round(score, 2)


def research_feature(feature: dict[str, Any]) -> dict[str, Any]:
    query = str(feature.get("query", "")).strip() or str(feature.get("name", ""))
    kind = str(feature.get("kind", "general"))
    candidates: list[dict[str, Any]] = []
    attempts: list[dict[str, Any]] = []
    for label, fn in (
        ("ProviderCatalog", lambda: static_provider_candidates(kind)),
        ("GitHub", lambda: github_repositories(query)),
        ("npm", lambda: npm_packages(query) if kind in {"ui", "automation", "workflow", "general"} else []),
        ("HuggingFace", lambda: huggingface_models(query, kind) if kind in {"ai_image", "media_video", "vision"} else []),
    ):
        try:
            found = fn()
            candidates.extend(found)
            attempts.append({"source": label, "status": "pass", "candidate_count": len(found)})
        except Exception as exc:
            attempts.append({"source": label, "status": "failed", "error": str(exc)[:300]})
    for candidate in candidates:
        candidate["score"] = candidate_score(candidate, query, kind)
    ranked_all = sorted(candidates, key=lambda row: (-float(row.get("score") or 0), str(row.get("name", ""))))[:10]
    ranked = [row for row in ranked_all if float(row.get("score") or 0) >= 10.0]
    recommendation = ranked[0] if ranked else {}
    return {
        "feature": feature,
        "query": query,
        "attempts": attempts,
        "candidates": ranked or ranked_all[:3],
        "recommended": recommendation,
        "decision": {
            "selected_name": recommendation.get("name", ""),
            "selected_source": recommendation.get("source", ""),
            "why": "Highest scored relevant candidate from market research evidence." if recommendation else "No reliable candidate found; provider must propose and justify a custom approach.",
            "must_verify_at_runtime": kind in {"ai_image", "media_video", "automation"},
        },
    }


def run_market_research(goal: str, blueprint: dict[str, Any], online_inputs: dict[str, Any], out_dir: pathlib.Path) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    features = infer_domain_features(goal, blueprint)
    feature_research = [research_feature(feature) for feature in features]
    manifest = {
        "kind": "MarketResearchManifest",
        "created_at": now(),
        "goal": goal,
        "strategy": "feature-by-feature online market research using public source APIs and provider catalogs",
        "features": features,
        "feature_research": feature_research,
        "online_input_context": {
            "project_type": online_inputs.get("project_type") if isinstance(online_inputs, dict) else "",
            "image_generation_model_count": len(online_inputs.get("image_generation_models", [])) if isinstance(online_inputs, dict) else 0,
        },
        "policy": "Generation should use these findings to choose libraries/models/APIs per feature, and explain deviations.",
    }
    (out_dir / "market_research.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    parser = argparse.ArgumentParser()
    parser.add_argument("--goal", required=True)
    parser.add_argument("--blueprint", default="")
    parser.add_argument("--online-inputs", default="")
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    blueprint = json.loads(pathlib.Path(args.blueprint).read_text(encoding="utf-8")) if args.blueprint else {}
    online_inputs = json.loads(pathlib.Path(args.online_inputs).read_text(encoding="utf-8")) if args.online_inputs else {}
    result = run_market_research(args.goal, blueprint, online_inputs, pathlib.Path(args.out_dir).resolve())
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"MARKET_RESEARCH: features={len(result['feature_research'])}")
        print(pathlib.Path(args.out_dir).resolve() / "market_research.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
