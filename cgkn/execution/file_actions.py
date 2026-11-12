"""Shared bounded candidate file actions; Host publication remains separate."""
import pathlib
from typing import Any, Mapping

ALLOWED_ACTIONS = {"read_file", "list_files", "write_file", "patch_file", "run_tests"}
PROTECTED_PARTS = {".git", ".hg", ".svn", ".cgkn-publication.lock"}

class ProposalError(ValueError):
    pass


class BoundedFileActions:
    def __init__(self, root: pathlib.Path | str):
        self.root = pathlib.Path(root).resolve()

    def _path(self, value: object) -> pathlib.Path:
        raw = str(value or ".")
        lexical = self.root / raw
        for item in (lexical, *lexical.parents):
            if item == self.root: break
            if item.is_symlink() or getattr(item, 'is_junction', lambda: False)():
                raise PermissionError("linked candidate paths are forbidden")
        candidate = lexical.resolve()
        if candidate != self.root and self.root not in candidate.parents:
            raise PermissionError("path escapes project root")
        relative = candidate.relative_to(self.root)
        if any(part.lower() in PROTECTED_PARTS for part in relative.parts):
            raise PermissionError("protected path rejected")
        return candidate

    def apply(self, action: Mapping[str, Any]) -> dict[str, Any]:
        kind = str(action.get("action", ""))
        allowed_fields = {
            "read_file": {"action", "path"}, "list_files": {"action", "path"},
            "write_file": {"action", "path", "content"}, "patch_file": {"action", "path", "find", "replace"},
        }
        if kind not in ALLOWED_ACTIONS or set(action) != allowed_fields.get(kind):
            raise ProposalError(f"invalid or over-broad worker action: {kind}")
        path = self._path(action["path"])
        if kind == "read_file":
            return {"action": kind, "path": str(path.relative_to(self.root)).replace("\\", "/"), "content": path.read_text(encoding="utf-8")}
        if kind == "list_files":
            return {"action": kind, "files": sorted(str(item.relative_to(self.root)).replace("\\", "/") for item in path.rglob("*") if item.is_file())}
        path.parent.mkdir(parents=True, exist_ok=True)
        if kind == "write_file":
            content = str(action["content"])
        else:
            before = path.read_text(encoding="utf-8")
            find = str(action["find"])
            if not find or before.count(find) != 1:
                raise ProposalError("patch find text must occur exactly once")
            content = before.replace(find, str(action["replace"]), 1)
        path.write_text(content, encoding="utf-8")
        return {"action": kind, "path": str(path.relative_to(self.root)).replace("\\", "/"), "bytes": len(content.encode("utf-8"))}




WORKER_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["schema_version", "node_id", "summary", "actions", "expected_outputs", "confidence", "needs_escalation", "escalation_reason"],
    "properties": {
        "schema_version": {"const": "1.0"}, "node_id": {"type": "string"}, "summary": {"type": "string"},
        "actions": {"type": "array", "items": {"oneOf": [
            {"type":"object","additionalProperties":False,"required":["action","path"],"properties":{"action":{"const":"run_tests"},"path":{"type":"string","description":"Relative candidate test file or directory; no options or commands"}}},
            {"type": "object", "additionalProperties": False, "required": ["action", "path"], "properties": {"action": {"const": "read_file"}, "path": {"type": "string"}}},
            {"type": "object", "additionalProperties": False, "required": ["action", "path"], "properties": {"action": {"const": "list_files"}, "path": {"type": "string"}}},
            {"type": "object", "additionalProperties": False, "required": ["action", "path", "content"], "properties": {"action": {"const": "write_file"}, "path": {"type": "string"}, "content": {"type": "string"}}},
            {"type": "object", "additionalProperties": False, "required": ["action", "path", "find", "replace"], "properties": {"action": {"const": "patch_file"}, "path": {"type": "string"}, "find": {"type": "string"}, "replace": {"type": "string"}}},
        ]}}, "expected_outputs": {"type": "array", "items": {"type": "string"}},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1}, "needs_escalation": {"type": "boolean"}, "escalation_reason": {"type": "string"},
    },
}


def scoped_worker_schema(contract, node_id):
    """Public write choices derive from the same admitted target_scope as execution."""
    from copy import deepcopy
    schema=deepcopy(WORKER_SCHEMA)
    schema['properties']['node_id']={'const':node_id}
    if 'local_process' not in contract.get('effect_domains',()):
        schema['properties']['actions']['items']['oneOf']=[b for b in schema['properties']['actions']['items']['oneOf'] if b['properties']['action']['const']!='run_tests']
    paths=sorted({str(pathlib.PurePosixPath(p.replace('\\','/'))) for p in contract['target_scope']})
    for branch in schema['properties']['actions']['items']['oneOf']:
        if branch['properties']['action']['const'] in {'write_file','patch_file'}:
            branch['properties']['path']=({'type':'string','description':'An exact target or a file beneath component_roots; no links or protected paths'} if contract.get('component_roots') else {'enum':paths})
    return schema


def validate_worker_proposal(value: Mapping[str, Any], node_id: str) -> dict[str, Any]:
    required = set(WORKER_SCHEMA["required"])
    if set(value) != required or value.get("schema_version") != "1.0" or value.get("node_id") != node_id:
        raise ProposalError("worker proposal has invalid envelope")
    if not isinstance(value.get("actions"), list) or not isinstance(value.get("expected_outputs"), list):
        raise ProposalError("worker proposal arrays are invalid")
    confidence = value.get("confidence")
    if not isinstance(confidence, (int, float)) or not 0 <= confidence <= 1:
        raise ProposalError("worker confidence is invalid")
    seen_test=False
    for action in value["actions"]:
        if not isinstance(action, dict) or action.get("action") not in ALLOWED_ACTIONS:
            raise ProposalError("worker proposal contains a forbidden action")
        if seen_test and action['action']!='run_tests':raise ProposalError('file actions must precede local test observations in a batch')
        seen_test=seen_test or action['action']=='run_tests'
        fields = {"run_tests": {"action", "path"}, "read_file": {"action", "path"}, "list_files": {"action", "path"}, "write_file": {"action", "path", "content"}, "patch_file": {"action", "path", "find", "replace"}}
        if set(action) != fields[action["action"]] or any(not isinstance(v, str) for v in action.values()):
            raise ProposalError("worker action fields are invalid; no actions applied")
    if bool(value["needs_escalation"]) and value["actions"]:
        raise ProposalError("escalation proposal cannot contain actions")
    return dict(value)





def writable_path(contract, name):
    """One admission-derived rule for candidate writes and publication."""
    p = pathlib.PurePosixPath(name)
    if p.is_absolute() or '..' in p.parts or any(x in name for x in ('\\', ':')):
        return False
    if any(part.startswith('.') or part in {'__pycache__', 'inputs'} for part in p.parts):
        return False
    return name in contract['target_scope'] or any(
        name.startswith(root.rstrip('/') + '/') for root in contract.get('component_roots', ()))


def candidate_files(root, contract):
    actions = BoundedFileActions(root)
    names = set(contract['target_scope'])
    for directory in contract.get('component_roots', ()):
        path = actions._path(directory)
        for item in path.rglob('*'):
            name = item.relative_to(actions.root).as_posix()
            actions._path(name)
            if item.is_file() and writable_path(contract, name): names.add(name)
            if len(names)>contract.get('max_candidate_files',128):raise PermissionError('candidate file bound exceeded')
    if len(names) > contract.get('max_candidate_files', 128):
        raise PermissionError('candidate file bound exceeded')
    return sorted(names)
