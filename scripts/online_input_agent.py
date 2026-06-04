#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
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

SCRIPT_DIR = pathlib.Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import local_intent_router


COMMONS_API = "https://commons.wikimedia.org/w/api.php"
GITHUB_SEARCH_API = "https://api.github.com/search/repositories"
HUGGINGFACE_MODELS_API = "https://huggingface.co/api/models"
OPEN_METEO_SAMPLE = "https://api.open-meteo.com/v1/forecast?latitude=35.6895&longitude=139.6917&current=temperature_2m,wind_speed_10m"
OPEN_LIBRARY_SAMPLE = "https://openlibrary.org/search.json?q=software%20engineering&limit=5"
SEABORN_IRIS_CSV = "https://raw.githubusercontent.com/mwaskom/seaborn-data/master/iris.csv"
STOOQ_AAPL_CSV = "https://stooq.com/q/d/l/?s=aapl.us&i=d"
W3C_DUMMY_PDF = "https://www.w3.org/WAI/ER/tests/xhtml/testfiles/resources/pdf/dummy.pdf"
NYU_SAMPLE_INVOICE_PDF = "https://isaw.nyu.edu/guide/finance/forms-docs/sample-vendor-invoice/at_download/file"
USER_AGENT = "CGNK-OnlineInputRouter/1.0"
GAMEPLAY_CATEGORY = "Category:Videos of video game gameplay"


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def safe_name(value: str) -> str:
    text = re.sub(r"[^a-zA-Z0-9_.-]+", "-", value).strip("-")
    return text[:120] or "online-input"


def request(url: str, timeout: int = 30) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "*/*"})
    last_error: Exception | None = None
    for attempt in range(6):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read()
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as exc:
            last_error = exc
            time.sleep(min(12.0, 1.5 * (attempt + 1)))
    raise RuntimeError(f"online input request failed after retries: {last_error}")


def get_json(url: str, timeout: int = 30) -> dict[str, Any]:
    doc = json.loads(request(url, timeout=timeout).decode("utf-8", errors="replace"))
    if not isinstance(doc, dict):
        raise RuntimeError("online input API returned non-object JSON")
    return doc


def get_json_value(url: str, timeout: int = 30) -> Any:
    return json.loads(request(url, timeout=timeout).decode("utf-8", errors="replace"))


def download(url: str, path: pathlib.Path, timeout: int = 120) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".part")
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "*/*"})
    last_error: Exception | None = None
    for attempt in range(6):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp, tmp.open("wb") as fh:
                while True:
                    chunk = resp.read(1024 * 1024)
                    if not chunk:
                        break
                    fh.write(chunk)
            tmp.replace(path)
            return
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as exc:
            last_error = exc
            try:
                tmp.unlink(missing_ok=True)
            except Exception:
                pass
            time.sleep(min(16.0, 2.0 * (attempt + 1)))
    raise RuntimeError(f"online input download failed after retries: {last_error}")


def keyword_tokens(goal: str, limit: int = 6) -> list[str]:
    words = re.findall(r"[a-zA-Z][a-zA-Z0-9_+#.-]{2,}", goal.lower())
    stop = {
        "the",
        "and",
        "for",
        "with",
        "from",
        "that",
        "this",
        "project",
        "build",
        "create",
        "make",
        "app",
        "tool",
        "system",
    }
    out: list[str] = []
    for word in words:
        if word not in stop and word not in out:
            out.append(word)
        if len(out) >= limit:
            break
    return out or ["example"]


def contains_any(text: str, needles: tuple[str, ...]) -> bool:
    return any(needle in text for needle in needles)


def media_query_for(goal: str, project_type: str) -> str:
    text = goal.lower()
    if contains_any(text, ("vn", "visual novel", "视觉小说", "立绘", "背景", "角色")):
        return "visual novel background character illustration"
    if contains_any(text, ("ocr", "文字识别", "票据", "发票", "document")):
        return "ocr document text photograph"
    if contains_any(text, ("object", "物体", "检测", "识别")):
        return "street photograph objects"
    if project_type == "media_audio":
        if contains_any(text, ("会议", "meeting")):
            return "speech meeting audio"
        return "speech audio"
    return " ".join(keyword_tokens(goal, 4) + ["photograph"])


def classify_project_type(goal: str) -> str:
    routed = local_intent_router.classify_project_type(goal)
    if routed.get("project_type") != "unknown_project_type":
        return str(routed["project_type"])
    text = goal.lower()
    tokens = set(re.findall(r"[a-z0-9_+#.-]+", text))
    phrase = f" {text} "
    if contains_any(text, ("股票", "股价", "行情", "金融数据", "stock", "equity", "finance", "trading")):
        return "financial_data"
    if contains_any(text, ("vn", "visual novel", "视觉小说", "立绘", "背景", "生成图")):
        return "media_image"
    if contains_any(text, ("video", "mp4", "clip", "highlight", "gameplay", "screen recording", "视频", "录像", "剪辑", "高光", "游戏录制")):
        return "media_video"
    if contains_any(text, ("image", "photo", "picture", "ocr", "vision", "detect objects", "segmentation", "图片", "图像", "照片", "立绘", "背景", "生成图", "物体检测", "视觉小说")):
        return "media_image"
    if tokens.intersection({"audio", "speech", "voice", "podcast", "transcribe", "transcription", "music"}) or contains_any(text, ("音频", "语音", "录音", "转文字", "会议纪要", "播客", "音乐")):
        return "media_audio"
    if any(word in phrase for word in (" csv ", " spreadsheet ", " table ", " dashboard ", " analytics ", " data analysis ", " bi ")) or contains_any(text, ("表格", "仪表盘", "数据分析", "报表", "电子表格")):
        return "tabular_data"
    if contains_any(text, ("machine learning", "ml", "classifier", "regression", "dataset", "model training", "机器学习", "分类器", "回归", "训练模型", "数据集")):
        return "ml_dataset"
    if contains_any(text, ("library", "sdk", "package", "cli", "command line", "developer tool", "命令行", "开发工具", "库", "包", "文档生成")):
        return "code_library"
    if contains_any(text, ("pdf", "document", "docx", "invoice", "resume", "contract", "文档", "发票", "票据", "简历", "合同")):
        return "document_processing"
    if contains_any(text, ("api", "backend", "server", "rest", "graphql", "webhook", "microservice", "后端", "接口", "服务器", "微服务", "返回 json", "返回json")):
        return "api_backend"
    if contains_any(text, ("scrape", "crawler", "website", "web page", "browser automation", "爬虫", "网页", "抓取", "浏览器自动化")):
        return "web_scraping"
    return "general_app"


def input_spec_for(project_type: str) -> dict[str, Any]:
    specs = {
        "media_video": {
            "required_modalities": ["video"],
            "preferred_sources": ["Wikimedia Commons"],
            "expected_artifacts": ["mp4_preview", "frame_preview", "analysis_report"],
        },
        "media_image": {
            "required_modalities": ["image"],
            "preferred_sources": ["Wikimedia Commons", "Hugging Face Hub text-to-image models"],
            "expected_artifacts": ["image_preview", "analysis_report", "image_generation_model_candidates"],
        },
        "media_audio": {
            "required_modalities": ["audio"],
            "preferred_sources": ["Wikimedia Commons"],
            "expected_artifacts": ["audio_file", "analysis_report"],
        },
        "tabular_data": {
            "required_modalities": ["csv"],
            "preferred_sources": ["OpenML", "public CSV"],
            "expected_artifacts": ["data_profile", "sample_rows"],
        },
        "financial_data": {
            "required_modalities": ["csv"],
            "preferred_sources": ["Stooq public market data"],
            "expected_artifacts": ["price_history_csv", "data_profile", "sample_rows"],
        },
        "ml_dataset": {
            "required_modalities": ["csv"],
            "preferred_sources": ["OpenML", "public CSV"],
            "expected_artifacts": ["data_profile", "baseline_test_report"],
        },
        "document_processing": {
            "required_modalities": ["pdf"],
            "preferred_sources": ["public PDF"],
            "expected_artifacts": ["document_metadata", "analysis_report"],
        },
        "api_backend": {
            "required_modalities": ["json"],
            "preferred_sources": ["Open-Meteo", "OpenLibrary"],
            "expected_artifacts": ["sample_request", "sample_response_json"],
        },
        "web_scraping": {
            "required_modalities": ["url", "html_snapshot"],
            "preferred_sources": ["public web page"],
            "expected_artifacts": ["source_url", "html_snapshot"],
        },
        "code_library": {
            "required_modalities": ["repository_metadata"],
            "preferred_sources": ["GitHub Search"],
            "expected_artifacts": ["repo_metadata", "example_usage_notes"],
        },
        "general_app": {
            "required_modalities": ["json", "repository_metadata"],
            "preferred_sources": ["OpenLibrary", "GitHub Search"],
            "expected_artifacts": ["sample_data", "example_source_metadata"],
        },
    }
    return {"project_type": project_type, **specs.get(project_type, specs["general_app"])}


def commons_candidates(search: str, media_prefix: str, limit: int = 20) -> list[dict[str, Any]]:
    params = {
        "action": "query",
        "generator": "search",
        "gsrnamespace": "6",
        "gsrsearch": search,
        "gsrlimit": str(limit),
        "prop": "imageinfo",
        "iiprop": "url|size|mime|extmetadata",
        "format": "json",
    }
    doc = get_json(COMMONS_API + "?" + urllib.parse.urlencode(params))
    pages = doc.get("query", {}).get("pages", {})
    out: list[dict[str, Any]] = []
    for page in pages.values() if isinstance(pages, dict) else []:
        if not isinstance(page, dict):
            continue
        info = page.get("imageinfo", [{}])[0]
        if not isinstance(info, dict):
            continue
        mime = str(info.get("mime", ""))
        url = str(info.get("url", ""))
        size = int(info.get("size", 0) or 0)
        if not url or not mime.startswith(media_prefix):
            continue
        ext = pathlib.PurePosixPath(urllib.parse.urlparse(url).path).suffix.lower() or ".bin"
        out.append(
            {
                "title": page.get("title", ""),
                "url": url,
                "mime": mime,
                "size": size,
                "extension": ext,
                "source": "Wikimedia Commons",
                "license": info.get("extmetadata", {}).get("LicenseShortName", {}).get("value", ""),
            }
        )
    return sorted(out, key=lambda row: int(row.get("size", 0)))


def commons_gameplay_candidates(limit: int = 25) -> list[dict[str, Any]]:
    params = {
        "action": "query",
        "generator": "categorymembers",
        "gcmtitle": GAMEPLAY_CATEGORY,
        "gcmtype": "file",
        "gcmlimit": str(limit),
        "prop": "imageinfo",
        "iiprop": "url|size|mime|extmetadata",
        "format": "json",
    }
    doc = get_json(COMMONS_API + "?" + urllib.parse.urlencode(params))
    pages = doc.get("query", {}).get("pages", {})
    out: list[dict[str, Any]] = []
    for page in pages.values() if isinstance(pages, dict) else []:
        info = page.get("imageinfo", [{}])[0] if isinstance(page, dict) else {}
        if not isinstance(info, dict):
            continue
        mime = str(info.get("mime", ""))
        url = str(info.get("url", ""))
        size = int(info.get("size", 0) or 0)
        if not url or not (mime.startswith("video/") or mime == "application/ogg"):
            continue
        ext = pathlib.PurePosixPath(urllib.parse.urlparse(url).path).suffix.lower() or ".webm"
        out.append(
            {
                "title": page.get("title", ""),
                "url": url,
                "mime": mime,
                "size": size,
                "extension": ext,
                "source": "Wikimedia Commons",
                "category": GAMEPLAY_CATEGORY,
                "license": info.get("extmetadata", {}).get("LicenseShortName", {}).get("value", ""),
            }
        )
    return sorted(out, key=lambda row: int(row.get("size", 0)))


def commons_file_candidate(title: str) -> dict[str, Any] | None:
    params = {
        "action": "query",
        "titles": title,
        "prop": "imageinfo",
        "iiprop": "url|size|mime|extmetadata",
        "format": "json",
    }
    doc = get_json(COMMONS_API + "?" + urllib.parse.urlencode(params))
    pages = doc.get("query", {}).get("pages", {})
    for page in pages.values() if isinstance(pages, dict) else []:
        if not isinstance(page, dict):
            continue
        info = page.get("imageinfo", [{}])[0]
        if not isinstance(info, dict):
            continue
        url = str(info.get("url", ""))
        if not url:
            continue
        return {
            "title": page.get("title", title),
            "url": url,
            "mime": str(info.get("mime", "")),
            "size": int(info.get("size", 0) or 0),
            "extension": pathlib.PurePosixPath(urllib.parse.urlparse(url).path).suffix.lower() or ".ogg",
            "source": "Wikimedia Commons",
            "license": info.get("extmetadata", {}).get("LicenseShortName", {}).get("value", ""),
        }
    return None


def choose_downloadable(candidates: list[dict[str, Any]], max_bytes: int) -> dict[str, Any] | None:
    for candidate in candidates:
        size = int(candidate.get("size", 0) or 0)
        if 0 < size <= max_bytes:
            return candidate
    return None


def add_downloaded_file(example: dict[str, Any], out_dir: pathlib.Path) -> dict[str, Any]:
    ext = str(example.get("extension", "")) or pathlib.PurePosixPath(urllib.parse.urlparse(str(example.get("url", ""))).path).suffix or ".bin"
    filename = safe_name(str(example.get("title", "online-input"))) + ext
    target = out_dir / filename
    download(str(example["url"]), target)
    example["local_path"] = str(target)
    example["downloaded_bytes"] = target.stat().st_size
    return example


def collect_media(goal: str, out_dir: pathlib.Path, project_type: str, max_bytes: int) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    attempts: list[dict[str, Any]] = []
    if project_type == "media_video":
        candidates = commons_gameplay_candidates() if any(word in goal.lower() for word in ("game", "gameplay", "highlight")) else commons_candidates("video file", "video/")
        attempts.append({"agent": "WikimediaMediaAgent", "source": "Wikimedia Commons", "candidate_count": len(candidates)})
        selected = choose_downloadable(candidates, max_bytes)
        if not selected:
            fallback = commons_file_candidate("File:Test-webM.webm")
            if fallback:
                attempts.append({"agent": "WikimediaMediaFallbackAgent", "source": "Wikimedia Commons", "title": "File:Test-webM.webm", "candidate_count": 1})
                selected = fallback if int(fallback.get("size", 0) or 0) <= max_bytes else None
        return ([add_downloaded_file({**selected, "modality": "video"}, out_dir)] if selected else []), attempts
    if project_type == "media_image":
        query = media_query_for(goal, project_type)
        candidates = commons_candidates(query, "image/")
        attempts.append({"agent": "WikimediaMediaAgent", "source": "Wikimedia Commons", "query": query, "candidate_count": len(candidates)})
        selected = choose_downloadable(candidates, max_bytes)
        return ([add_downloaded_file({**selected, "modality": "image"}, out_dir)] if selected else []), attempts
    if project_type == "media_audio":
        query = media_query_for(goal, project_type)
        candidates = commons_candidates(query, "audio/")
        if not candidates:
            fallback = commons_file_candidate("File:En-us-hello-4.ogg")
            if fallback:
                candidates = [fallback]
        attempts.append({"agent": "WikimediaMediaAgent", "source": "Wikimedia Commons", "query": query, "candidate_count": len(candidates)})
        selected = choose_downloadable(candidates, max_bytes)
        return ([add_downloaded_file({**selected, "modality": "audio"}, out_dir)] if selected else []), attempts
    return [], attempts


def image_generation_requested(goal: str) -> bool:
    text = goal.lower()
    return contains_any(
        text,
        (
            "生成图",
            "生成图片",
            "直接生成图片",
            "立绘",
            "背景",
            "character art",
            "background art",
            "image generation",
            "text-to-image",
            "ai generated",
            "stable diffusion",
            "flux",
            "dall",
        ),
    )


def collect_huggingface_text_to_image_models(goal: str, limit: int = 8) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    params = {
        "pipeline_tag": "text-to-image",
        "sort": "downloads",
        "direction": "-1",
        "limit": str(limit),
        "full": "true",
    }
    url = HUGGINGFACE_MODELS_API + "?" + urllib.parse.urlencode(params)
    doc = get_json_value(url)
    models = doc if isinstance(doc, list) else []
    out: list[dict[str, Any]] = []
    for item in models:
        if not isinstance(item, dict):
            continue
        model_id = str(item.get("modelId", "")).strip()
        if not model_id:
            continue
        tags = item.get("tags", [])
        tags_list = [str(tag) for tag in tags[:40]] if isinstance(tags, list) else []
        out.append(
            {
                "provider": "Hugging Face Hub",
                "model_id": model_id,
                "url": f"https://huggingface.co/{model_id}",
                "pipeline_tag": item.get("pipeline_tag", "text-to-image"),
                "downloads": item.get("downloads"),
                "likes": item.get("likes"),
                "tags": tags_list,
                "requires": ["HF_TOKEN or another configured Hugging Face Inference Provider credential"],
                "integration_hint": "Use Hugging Face Inference Providers or a compatible text-to-image SDK/API; do not copy model sample images as output.",
            }
        )
    return out, {"agent": "HuggingFaceTextToImageModelAgent", "source": "Hugging Face Hub API", "url": url, "candidate_count": len(out)}


def static_image_generation_providers() -> list[dict[str, Any]]:
    return [
        {
            "provider": "OpenAI Images API",
            "model_id": "gpt-image-1",
            "url": "https://platform.openai.com/docs/guides/image-generation",
            "requires": ["OPENAI_API_KEY", "OPENAI_BASE_URL that supports /images/generations or /responses image generation"],
            "integration_hint": "Use when the configured OpenAI-compatible endpoint explicitly supports image generation; first run a capability probe.",
        },
        {
            "provider": "Replicate",
            "model_id": "black-forest-labs/flux-schnell or another selected text-to-image model",
            "url": "https://replicate.com/docs",
            "requires": ["REPLICATE_API_TOKEN"],
            "integration_hint": "Use Replicate predictions API when a token is configured; choose the exact model from current Replicate catalog.",
        },
    ]


def collect_image_generation_model_candidates(goal: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    candidates = static_image_generation_providers()
    attempts: list[dict[str, Any]] = [{"agent": "StaticImageProviderCatalog", "source": "known provider docs", "candidate_count": len(candidates)}]
    try:
        hf_models, hf_attempt = collect_huggingface_text_to_image_models(goal)
        candidates.extend(hf_models)
        attempts.append(hf_attempt)
    except Exception as exc:
        attempts.append({"agent": "HuggingFaceTextToImageModelAgent", "source": "Hugging Face Hub API", "status": "failed", "error": str(exc)})
    return candidates, attempts


def collect_csv_example(goal: str, out_dir: pathlib.Path, project_type: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if project_type == "financial_data":
        target = out_dir / "aapl_daily_prices.csv"
        download(STOOQ_AAPL_CSV, target)
        title = "AAPL daily market data"
        source = "Stooq public market data"
        url = STOOQ_AAPL_CSV
        license_name = "public web data source"
    else:
        target = out_dir / "iris.csv"
        download(SEABORN_IRIS_CSV, target)
        title = "Iris tabular dataset"
        source = "public CSV mirror"
        url = SEABORN_IRIS_CSV
        license_name = "repository dataset example"
    rows = []
    with target.open("r", encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        for idx, row in enumerate(reader):
            rows.append(row)
            if idx >= 4:
                break
    return [
        {
            "title": title,
            "url": url,
            "source": source,
            "modality": "csv",
            "mime": "text/csv",
            "license": license_name,
            "local_path": str(target),
            "downloaded_bytes": target.stat().st_size,
            "sample_rows": rows,
        }
    ], [{"agent": "TabularDatasetAgent", "source": source, "candidate_count": 1}]


def collect_public_api_example(goal: str, out_dir: pathlib.Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    text = goal.lower()
    url = OPEN_LIBRARY_SAMPLE if any(word in text for word in ("book", "library", "search", "catalog")) else OPEN_METEO_SAMPLE
    doc = get_json(url)
    target = out_dir / ("openlibrary_sample.json" if "openlibrary" in url else "openmeteo_sample.json")
    target.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return [
        {
            "title": "Public API sample response",
            "url": url,
            "source": "OpenLibrary" if "openlibrary" in url else "Open-Meteo",
            "modality": "json",
            "mime": "application/json",
            "local_path": str(target),
            "downloaded_bytes": target.stat().st_size,
            "sample_keys": sorted(doc.keys())[:20],
        }
    ], [{"agent": "PublicApiExampleAgent", "source": "OpenLibrary/Open-Meteo", "candidate_count": 1}]


def collect_github_example(goal: str, out_dir: pathlib.Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    query = " ".join(keyword_tokens(goal, 5))
    params = {"q": query, "sort": "stars", "order": "desc", "per_page": "5"}
    doc = get_json(GITHUB_SEARCH_API + "?" + urllib.parse.urlencode(params))
    items = doc.get("items", [])
    target = out_dir / "github_repository_examples.json"
    target.write_text(json.dumps({"query": query, "items": items[:5]}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    examples: list[dict[str, Any]] = []
    for item in items[:3] if isinstance(items, list) else []:
        if not isinstance(item, dict):
            continue
        examples.append(
            {
                "title": item.get("full_name", ""),
                "url": item.get("html_url", ""),
                "source": "GitHub Search",
                "modality": "repository_metadata",
                "description": item.get("description", ""),
                "stars": item.get("stargazers_count", 0),
                "language": item.get("language", ""),
                "local_path": str(target),
            }
        )
    if not examples:
        fallback = {
            "title": "markdown-it/markdown-it",
            "url": "https://github.com/markdown-it/markdown-it",
            "source": "GitHub public repository",
            "modality": "repository_metadata",
            "description": "Markdown parser reference repository used when GitHub search returns no suitable result.",
            "stars": None,
            "language": "JavaScript",
            "local_path": str(target),
        }
        target.write_text(json.dumps({"query": query, "items": [fallback], "fallback": True}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        examples = [fallback]
    return examples, [{"agent": "GitHubExampleAgent", "source": "GitHub Search", "query": query, "candidate_count": len(examples)}]


def collect_document_example(out_dir: pathlib.Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    target = out_dir / "sample_invoice.pdf"
    url = NYU_SAMPLE_INVOICE_PDF
    source = "NYU public sample invoice"
    title = "NYU sample vendor invoice"
    try:
        download(url, target)
    except Exception:
        target = out_dir / "sample_document.pdf"
        url = W3C_DUMMY_PDF
        source = "W3C public test resource"
        title = "W3C dummy PDF"
        download(url, target)
    return [
        {
            "title": title,
            "url": url,
            "source": source,
            "modality": "pdf",
            "mime": "application/pdf",
            "local_path": str(target),
            "downloaded_bytes": target.stat().st_size,
        }
    ], [{"agent": "DocumentExampleAgent", "source": source, "candidate_count": 1}]


def collect_web_page_example(out_dir: pathlib.Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    url = "https://example.com/"
    html = request(url).decode("utf-8", errors="replace")
    target = out_dir / "public_page_snapshot.html"
    target.write_text(html, encoding="utf-8")
    return [
        {
            "title": "Example.com public page",
            "url": url,
            "source": "IANA reserved example domain",
            "modality": "html_snapshot",
            "mime": "text/html",
            "local_path": str(target),
            "downloaded_bytes": target.stat().st_size,
        }
    ], [{"agent": "WebPageExampleAgent", "source": "example.com", "candidate_count": 1}]


def route_collectors(goal: str, out_dir: pathlib.Path, project_type: str, max_bytes: int) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if project_type in {"media_video", "media_image", "media_audio"}:
        return collect_media(goal, out_dir, project_type, max_bytes)
    if project_type in {"tabular_data", "ml_dataset", "financial_data"}:
        return collect_csv_example(goal, out_dir, project_type)
    if project_type == "document_processing":
        return collect_document_example(out_dir)
    if project_type == "api_backend":
        return collect_public_api_example(goal, out_dir)
    if project_type == "web_scraping":
        return collect_web_page_example(out_dir)
    if project_type == "code_library":
        return collect_github_example(goal, out_dir)

    examples, attempts = collect_public_api_example(goal, out_dir)
    try:
        repos, repo_attempts = collect_github_example(goal, out_dir)
        examples.extend(repos[:2])
        attempts.extend(repo_attempts)
    except Exception as exc:
        attempts.append({"agent": "GitHubExampleAgent", "status": "failed", "error": str(exc)})
    return examples, attempts


def collect_online_inputs(goal: str, out_dir: pathlib.Path, max_bytes: int = 25_000_000) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    project_type = classify_project_type(goal)
    input_spec = input_spec_for(project_type)
    errors: list[dict[str, Any]] = []
    try:
        examples, attempts = route_collectors(goal, out_dir, project_type, max_bytes)
    except Exception as exc:
        errors.append({"agent": "OnlineInputRouter", "error": str(exc)})
        if project_type not in {"general_app", "api_backend"}:
            examples, attempts = collect_public_api_example(goal, out_dir)
            attempts.append({"agent": "FallbackRoute", "reason": "primary route failed; used public JSON sample"})
        else:
            raise
    if not examples:
        raise RuntimeError(f"no online input examples found for project_type={project_type}")
    image_generation_models: list[dict[str, Any]] = []
    if project_type == "media_image" and image_generation_requested(goal):
        image_generation_models, model_attempts = collect_image_generation_model_candidates(goal)
        attempts.extend(model_attempts)

    manifest = {
        "kind": "OnlineInputExamples",
        "created_at": now(),
        "goal": goal,
        "agent": "online_input_router",
        "project_type": project_type,
        "input_spec": input_spec,
        "routing": {
            "strategy": "classify project type, build input spec, then route to a source-specific example agent",
            "attempts": attempts,
            "errors": errors,
        },
        "policy": "Use public online examples as realistic test input; preserve source and license metadata when available. For requested AI image generation, use model candidates as integration targets, not as copied output images.",
        "examples": examples,
        "image_generation_models": image_generation_models,
    }
    (out_dir / "online_input_examples.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--goal", required=True)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--max-bytes", type=int, default=25_000_000)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    result = collect_online_inputs(args.goal, pathlib.Path(args.out_dir).resolve(), args.max_bytes)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        first = result["examples"][0]
        print(first.get("local_path") or first.get("url") or result["project_type"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
