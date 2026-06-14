#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import pathlib
import re
import sys
import time
from datetime import datetime, timezone
from typing import Any, Callable

SCRIPTS_DIR = pathlib.Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import check_connectivity
import local_agent_actions


AgentCallable = Callable[[list[dict[str, Any]], str, int], str | dict[str, Any]]


SYSTEM_PROMPT = """You are the CGNK local project generation agent.
You receive the complete persisted conversation history and must improve the project through actions.
Return JSON only:
{
  "message": "short reasoning or status",
  "actions": [
    {"type": "write_file", "path": "README.md", "content": "..."},
    {"type": "read_file", "path": "README.md"},
    {"type": "list_files", "path": "."},
    {"type": "run_command", "command": "python app.py"},
    {"type": "capture_screenshot", "path": "artifacts/screenshot.txt"},
    {"type": "search_skills", "query": "test api screenshot"},
    {"type": "use_skill", "name": "patch_file", "args": {"path": "README.md", "find": "old", "replace": "new"}},
    {"type": "propose_skill", "name": "sqlite_query", "description": "...", "manifest": {}, "notes": "..."},
    {"type": "package_project", "startup_command": "python app.py", "known_limits": []},
    {"type": "final_message", "text": "What to tell the customer"}
  ]
}
Do not claim delivery is ready. Only the local package_project action can create final delivery.
Use failed tool results to repair the project before trying package_project again.
You may use search_skills to discover approved local skills.
You may use use_skill to call approved local skills.
You may use propose_skill to draft a missing skill, but draft skills are not automatically approved.
Prefer existing skills before inventing new ones.
Skill failures are tool results; inspect them and repair the project.
Do not claim delivery is ready unless package_project creates a delivery manifest.
For local web apps, prefer run_tests/http_request/browser_screenshot when useful.
For small edits, prefer patch_file over rewriting the whole file."""


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def append_event(session_path: pathlib.Path, event: dict[str, Any]) -> None:
    session_path.parent.mkdir(parents=True, exist_ok=True)
    event.setdefault("created_at", now())
    with session_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(event, ensure_ascii=False) + "\n")


def read_session(session_path: pathlib.Path) -> list[dict[str, Any]]:
    if not session_path.exists():
        return []
    events: list[dict[str, Any]] = []
    for line in session_path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            doc = json.loads(line)
        except Exception:
            continue
        if isinstance(doc, dict):
            events.append(doc)
    return events


def _extract_json_object(text: str) -> dict[str, Any]:
    raw = str(text or "").strip()
    parse_error = ""
    try:
        doc = json.loads(raw)
        if isinstance(doc, dict):
            return doc
    except Exception as exc:
        parse_error = str(exc)
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, flags=re.S | re.I)
    if fenced:
        try:
            doc = json.loads(fenced.group(1))
            if isinstance(doc, dict):
                return doc
        except Exception:
            pass
    match = re.search(r"\{.*\}", raw, flags=re.S)
    if match:
        try:
            doc = json.loads(match.group(0))
            if isinstance(doc, dict):
                return doc
        except Exception as exc:
            parse_error = str(exc)
    fallback = {"message": raw, "actions": _salvage_complete_write_file_actions(raw)}
    if parse_error:
        fallback["_parse_error"] = parse_error
    return fallback


def _decode_json_string_fragment(value: str) -> str:
    return json.loads(f'"{value}"')


def _salvage_complete_write_file_actions(raw: str) -> list[dict[str, Any]]:
    """Recover fully closed write_file actions from a truncated agent JSON reply."""
    actions: list[dict[str, Any]] = []
    pattern = re.compile(
        r'\{\s*"type"\s*:\s*"write_file"\s*,\s*"path"\s*:\s*"((?:\\.|[^"\\])*)"\s*,\s*"content"\s*:\s*"((?:\\.|[^"\\])*)"\s*\}',
        flags=re.S,
    )
    for match in pattern.finditer(raw):
        try:
            path = _decode_json_string_fragment(match.group(1))
            content = _decode_json_string_fragment(match.group(2))
        except Exception:
            continue
        if path.strip():
            actions.append({"type": "write_file", "path": path, "content": content})
    return actions


def parse_agent_response(response: str | dict[str, Any]) -> dict[str, Any]:
    if isinstance(response, dict):
        doc = response
    else:
        doc = _extract_json_object(str(response))
    actions = doc.get("actions", [])
    if isinstance(doc.get("action"), dict):
        actions = [doc["action"]]
    if not isinstance(actions, list):
        actions = []
    clean_actions = [action for action in actions if isinstance(action, dict)]
    result = {"message": str(doc.get("message", "")), "actions": clean_actions, "raw": response}
    if doc.get("_parse_error"):
        result["parse_error"] = str(doc.get("_parse_error"))
    return result


def _history_for_agent(events: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for event in events:
        kind = str(event.get("kind") or event.get("role") or "event")
        payload = json.dumps(event, ensure_ascii=False)
        lines.append(f"{kind}: {payload}")
    return "\n".join(lines)[-60000:]


def call_default_agent(events: list[dict[str, Any]], model: str, timeout: int) -> str:
    creds = check_connectivity._resolve_api_credentials()
    token = str(creds.get("api_key", "")).strip()
    if not token:
        raise RuntimeError("missing OpenAI-compatible API key for agent conversation loop")
    root = str(creds.get("base_url", "")).rstrip("/")
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": _history_for_agent(events)},
    ]
    endpoint = check_connectivity._openai_compatible_endpoint(root)
    payload = check_connectivity._build_openai_compatible_payload(
        root,
        {"model": model, "messages": messages, "temperature": 0.2, "max_tokens": 6000},
    )
    last_error = ""
    for attempt in range(4):
        doc, error = check_connectivity._post_json(endpoint, payload, token, timeout)
        if doc is not None:
            text = check_connectivity._extract_text(doc)
            if text:
                return text
        last_error = error
        if not check_connectivity._error_is_retryable(error):
            break
        time.sleep(min(8.0, 1.5 * (attempt + 1)))
    raise RuntimeError(f"provider_api_request_failed: {last_error}" if last_error else "empty agent response")


def run_agent_loop(
    *,
    session_path: str | pathlib.Path,
    project_dir: str | pathlib.Path,
    model: str = "gpt-4.1",
    timeout: int = 120,
    max_turns: int = 12,
    agent: AgentCallable | None = None,
) -> dict[str, Any]:
    session_file = pathlib.Path(session_path).resolve()
    project = pathlib.Path(project_dir).resolve()
    executor = local_agent_actions.LocalAgentActionExecutor(project)
    agent_fn = agent or call_default_agent
    package_result: dict[str, Any] | None = None
    turns = 0
    repair_turn_used = False
    allowed_turns = max(1, int(max_turns))

    while turns < allowed_turns:
        turns += 1
        events = read_session(session_file)
        try:
            response = agent_fn(events, model, timeout)
        except Exception as exc:
            append_event(session_file, {"kind": "agent_error", "role": "assistant", "error": str(exc), "turn": turns})
            return {"status": "failed", "error": str(exc), "turns": turns, "session_path": str(session_file), "project_dir": str(project)}

        parsed = parse_agent_response(response)
        append_event(
            session_file,
            {
                "kind": "assistant",
                "role": "assistant",
                "turn": turns,
                "message": parsed.get("message", ""),
                "actions": parsed.get("actions", []),
            },
        )

        actions = parsed.get("actions", [])
        if not actions:
            append_event(session_file, {"kind": "tool_result", "turn": turns, "ok": False, "error": "agent returned no actions"})
        failed_this_turn = False
        for action in actions:
            action_type = str(action.get("type") or action.get("action") or "")
            append_event(session_file, {"kind": "action", "turn": turns, "action": action})
            if action_type == "final_message":
                result = {"ok": True, "type": "final_message", "text": str(action.get("text", ""))}
            else:
                result = executor.execute(action)
            append_event(session_file, {"kind": "tool_result", "turn": turns, "action": action, "result": result})
            if not result.get("ok"):
                failed_this_turn = True
            if action_type == "package_project" and result.get("ok"):
                package_result = result
                break
        if package_result:
            manifest = package_result.get("manifest", {}) if isinstance(package_result.get("manifest"), dict) else {}
            return {
                "status": str(manifest.get("status") or "ready"),
                "turns": turns,
                "session_path": str(session_file),
                "project_dir": str(project),
                "manifest": manifest,
                "package_path": manifest.get("package_path", ""),
                "manifest_path": manifest.get("manifest_path", ""),
            }
        if failed_this_turn and turns >= allowed_turns and not repair_turn_used:
            repair_turn_used = True
            allowed_turns += 1
            append_event(session_file, {"kind": "repair_prompt", "turn": turns, "message": "A failed action was returned to the agent for one repair attempt."})
            continue
        if turns >= allowed_turns:
            break

    return {"status": "max_turns_reached", "turns": turns, "session_path": str(session_file), "project_dir": str(project)}


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Run the CGNK local agent conversation loop.")
    parser.add_argument("--session-path", required=True)
    parser.add_argument("--project-dir", required=True)
    parser.add_argument("--model", default=os.environ.get("OPENAI_MODEL", "gpt-4.1"))
    parser.add_argument("--timeout", type=int, default=120)
    parser.add_argument("--max-turns", type=int, default=12)
    args = parser.parse_args()
    result = run_agent_loop(
        session_path=args.session_path,
        project_dir=args.project_dir,
        model=args.model,
        timeout=args.timeout,
        max_turns=args.max_turns,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
