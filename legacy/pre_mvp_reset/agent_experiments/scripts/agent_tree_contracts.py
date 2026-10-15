from __future__ import annotations

import json
import pathlib
import re
from datetime import datetime, timezone
from typing import Any


DEFAULT_EVAL_DIR = pathlib.Path("generated/agent_tree_rebuild_eval")
DEFAULT_PROJECT_ID = "goal-driven-local-project"
DEFAULT_ALLOWED_CONTEXT_TERMS = [
    "local first",
    "runnable application",
    "goal specific behavior",
    "tests",
    "readme",
    "delivery bundle",
]
DEFAULT_FORBIDDEN_CONTEXT_TERMS = [
    "视频",
    "鉴挂",
    "背景",
    "立绘",
    "鼠标键盘动作",
    "sprite",
    "video material",
    "image generation demo",
    "unrelated product template",
    "placeholder-only implementation",
]


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", value.strip().lower()).strip("-")
    return slug or DEFAULT_PROJECT_ID


def write_json(path: str | pathlib.Path, doc: dict[str, Any]) -> pathlib.Path:
    target = pathlib.Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return target


def read_json(path: str | pathlib.Path, default: dict[str, Any] | None = None) -> dict[str, Any]:
    target = pathlib.Path(path)
    if not target.exists():
        return dict(default or {})
    try:
        doc = json.loads(target.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return dict(default or {})
    return doc if isinstance(doc, dict) else dict(default or {})


def append_jsonl(path: str | pathlib.Path, doc: dict[str, Any]) -> pathlib.Path:
    target = pathlib.Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(doc, ensure_ascii=False) + "\n")
    return target


def read_jsonl(path: str | pathlib.Path) -> list[dict[str, Any]]:
    target = pathlib.Path(path)
    if not target.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in target.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            doc = json.loads(line)
        except Exception:
            continue
        if isinstance(doc, dict):
            rows.append(doc)
    return rows


def contains_forbidden_terms(value: Any, forbidden_terms: list[str]) -> list[str]:
    text = json.dumps(value, ensure_ascii=False).lower() if not isinstance(value, str) else value.lower()
    return [term for term in forbidden_terms if term.lower() in text]


def rel_list(project_dir: pathlib.Path, paths: list[pathlib.Path]) -> list[str]:
    result: list[str] = []
    for path in paths:
        try:
            result.append(path.relative_to(project_dir).as_posix())
        except ValueError:
            result.append(str(path))
    return result
