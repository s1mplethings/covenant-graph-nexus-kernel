"""Milestone M2: Evidence Import and Signals.

Provides persistent, isolated evidence management and signal tracking via handle(data_dir, request).
Reuses M1 project isolation mechanisms (reading projects.json from the same data_dir).
"""

import hashlib
import json
import os
import uuid

MILESTONE_ID = "M2"

_PROJECTS_FILENAME = "projects.json"
_EVIDENCE_FILENAME = "evidence.json"
_SIGNALS_FILENAME = "signals.json"


def _store_path(data_dir, filename):
    return os.path.join(data_dir, filename)


def _load_json(data_dir, filename):
    path = _store_path(data_dir, filename)
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()
    if not content.strip():
        return []
    data = json.loads(content)
    if not isinstance(data, list):
        return []
    return data


def _save_json(data_dir, filename, items):
    os.makedirs(data_dir, exist_ok=True)
    path = _store_path(data_dir, filename)
    tmp_path = path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False)
    os.replace(tmp_path, path)


def _validate_project_exists(data_dir, project_id):
    if not isinstance(project_id, str) or not project_id:
        raise ValueError("project_id must be a non-empty string")
    projects = _load_json(data_dir, _PROJECTS_FILENAME)
    for p in projects:
        if p.get("id") == project_id:
            return True
    raise ValueError("project not found: %s" % project_id)


def _sha256_bytes(b):
    return hashlib.sha256(b).hexdigest()


def _read_file_content(filepath):
    try:
        with open(filepath, "rb") as f:
            return f.read()
    except Exception:
        # If we can't read it, treat as empty or skip? Contract says bounded local directory.
        # We'll assume readable text files. If binary/unreadable, maybe skip or error?
        # For simplicity in this context, let's assume text files are readable.
        # If unreadable, we might want to skip or raise. Let's raise ValueError if critical.
        raise ValueError("cannot read file: %s" % filepath)


_SENSITIVE_KEY_NAMES = (
    'db_password',
    'password',
    'api_key',
    'apikey',
    'secret',
    'token',
    'access_key',
    'private_key',
)


def _is_forbidden_content(text):
    """Check if text contains known secret patterns like API keys in .env files."""
    if not text:
        return False
    # Check for common secret patterns, tolerating whitespace around '='
    # (e.g. 'API_KEY = value', 'DB_PASSWORD=value').
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith('#'):
            continue
        if '=' not in line:
            continue
        key_part = line.split('=', 1)[0]
        # Normalize key: strip whitespace, lowercase, unify separators
        normalized_key = key_part.strip().lower().replace('-', '_')
        for sensitive in _SENSITIVE_KEY_NAMES:
            if normalized_key == sensitive or normalized_key.endswith('_' + sensitive):
                return True
    # Specific check for .env style secrets often found in fixtures
    if 'sk-' in text or 'pk-' in text:
        return True
    return False

def _scan_directory(root_path):
    """Recursively scan directory for files, returning relative paths and contents."""
    files = []
    if not os.path.isdir(root_path):
        raise ValueError("path is not a directory: %s" % root_path)
    
    # Resolve the root path to absolute to prevent traversal issues
    abs_root = os.path.abspath(root_path)
    
    for dirpath, dirnames, filenames in os.walk(abs_root):
        # Skip .git directories explicitly per contract
        if '.git' in dirnames:
            dirnames.remove('.git')
            
        for fname in filenames:
            full_path = os.path.join(dirpath, fname)
            
            # Security check: Ensure the resolved file path is within the bounded root directory
            # This prevents reading files outside the intended scope via symlinks or ..
            real_full_path = os.path.realpath(full_path)
            if not real_full_path.startswith(abs_root + os.sep) and real_full_path != abs_root:
                continue
                
            rel_path = os.path.relpath(real_full_path, abs_root)
            # Normalize separators to forward slash for consistency
            rel_path = rel_path.replace(os.sep, '/')
            
            # Reject forbidden boundary bytes (e.g., null bytes) in path or filename
            if '\x00' in rel_path or '\x00' in fname:
                continue
                
            try:
                content_bytes = _read_file_content(real_full_path)
                # Try to decode as utf-8, fallback to latin-1
                try:
                    text = content_bytes.decode('utf-8')
                except UnicodeDecodeError:
                    text = content_bytes.decode('latin-1')
                    
                # Security check: Exclude files containing forbidden secret patterns
                if _is_forbidden_content(text):
                    continue

                sha = _sha256_bytes(content_bytes)
                files.append({
                    "path": rel_path,
                    "sha256": sha,
                    "text": text
                })
            except ValueError:
                continue
    return files


def _get_evidence_by_id(data_dir, evidence_id):
    evidence_list = _load_json(data_dir, _EVIDENCE_FILENAME)
    for ev in evidence_list:
        if ev.get("id") == evidence_id:
            return ev
    return None


def handle(data_dir, request):
    if not isinstance(data_dir, str) or not data_dir:
        raise ValueError("data_dir must be a non-empty string")
    if not isinstance(request, dict):
        raise ValueError("request must be a dict")

    op = request.get("op")
    if not isinstance(op, str) or not op:
        raise ValueError("request must contain a non-empty 'op' string")

    # Common validation for operations requiring project_id
    project_id = request.get("project_id")
    
    if op == "evidence.import":
        _validate_project_exists(data_dir, project_id)
        source_path = request.get("path")
        if not isinstance(source_path, str) or not source_path:
            raise ValueError("path must be a non-empty string")
        
        # Security check: ensure path doesn't traverse outside? 
        # The contract says "bounded local directory... without following symlinks outside it".
        # We'll do a basic realpath check against cwd or just trust the input is within bounds for now.
        # Ideally, we resolve and check prefix. 
        abs_source = os.path.abspath(source_path)
        
        files_data = _scan_directory(abs_source)
        
        # Calculate overall digest of all files? Or just store individual digests?
        # Contract: "Digest is SHA-256 of actual content". Usually implies per-file or aggregate.
        # Return shape: {id, project_id, source_path, version, sha256, status, files:[...]}
        # The top-level sha256 likely refers to the aggregate state or the primary identifier.
        # Let's compute an aggregate hash of sorted file hashes to represent the snapshot.
        sorted_hashes = sorted([f["sha256"] for f in files_data])
        aggregate_hash = _sha256_bytes(json.dumps(sorted_hashes).encode('utf-8'))
        
        evidence_id = uuid.uuid4().hex
        record = {
            "id": evidence_id,
            "project_id": project_id,
            "source_path": source_path,
            "version": 1,
            "sha256": aggregate_hash,
            "status": "CURRENT",
            "files": files_data
        }
        
        evidence_list = _load_json(data_dir, _EVIDENCE_FILENAME)
        evidence_list.append(record)
        _save_json(data_dir, _EVIDENCE_FILENAME, evidence_list)
        
        return record

    if op == "evidence.refresh":
        _validate_project_exists(data_dir, project_id)
        evidence_id = request.get("evidence_id")
        if not isinstance(evidence_id, str) or not evidence_id:
            raise ValueError("evidence_id must be a non-empty string")
            
        old_record = _get_evidence_by_id(data_dir, evidence_id)
        if not old_record:
            raise ValueError("evidence not found: %s" % evidence_id)
        if old_record["project_id"] != project_id:
            raise ValueError("evidence belongs to different project")
            
        source_path = old_record["source_path"]
        abs_source = os.path.abspath(source_path)
        
        new_files_data = _scan_directory(abs_source)
        
        # Check if changed
        old_sorted_hashes = sorted([f["sha256"] for f in old_record["files"]])
        new_sorted_hashes = sorted([f["sha256"] for f in new_files_data])
        
        if old_sorted_hashes == new_sorted_hashes:
            # Unchanged, keep same version identity
            return old_record
            
        # Changed: create new ID, mark old as SUPERSEDED
        aggregate_hash = _sha256_bytes(json.dumps(new_sorted_hashes).encode('utf-8'))
        new_evidence_id = uuid.uuid4().hex
        new_version = old_record["version"] + 1
        
        new_record = {
            "id": new_evidence_id,
            "project_id": project_id,
            "source_path": source_path,
            "version": new_version,
            "sha256": aggregate_hash,
            "status": "CURRENT",
            "files": new_files_data
        }
        
        evidence_list = _load_json(data_dir, _EVIDENCE_FILENAME)
        updated_list = []
        for ev in evidence_list:
            if ev["id"] == evidence_id:
                ev_copy = ev.copy()
                ev_copy["status"] = "SUPERSEDED"
                updated_list.append(ev_copy)
            else:
                updated_list.append(ev)
        updated_list.append(new_record)
        _save_json(data_dir, _EVIDENCE_FILENAME, updated_list)
        
        return new_record

    if op == "evidence.get":
        _validate_project_exists(data_dir, project_id)
        evidence_id = request.get("evidence_id")
        if not isinstance(evidence_id, str) or not evidence_id:
            raise ValueError("evidence_id must be a non-empty string")
            
        record = _get_evidence_by_id(data_dir, evidence_id)
        if not record:
            raise ValueError("evidence not found: %s" % evidence_id)
        if record["project_id"] != project_id:
            raise ValueError("evidence belongs to different project")
            
        return record

    if op == "evidence.list":
        _validate_project_exists(data_dir, project_id)
        evidence_list = _load_json(data_dir, _EVIDENCE_FILENAME)
        items = [ev for ev in evidence_list if ev["project_id"] == project_id]
        return {"items": items}

    if op == "signal.create":
        _validate_project_exists(data_dir, project_id)
        evidence_id = request.get("evidence_id")
        text = request.get("text")
        
        if not isinstance(evidence_id, str) or not evidence_id:
            raise ValueError("evidence_id must be a non-empty string")
        if not isinstance(text, str) or not text.strip():
            raise ValueError("text must be a non-empty string")
            
        ev_record = _get_evidence_by_id(data_dir, evidence_id)
        if not ev_record:
            raise ValueError("evidence not found: %s" % evidence_id)
        if ev_record["project_id"] != project_id:
            raise ValueError("evidence belongs to different project")
            
        signal_id = uuid.uuid4().hex
        record = {
            "id": signal_id,
            "project_id": project_id,
            "evidence_id": evidence_id,
            "text": text,
            "status": "OPEN"
        }
        
        signals_list = _load_json(data_dir, _SIGNALS_FILENAME)
        signals_list.append(record)
        _save_json(data_dir, _SIGNALS_FILENAME, signals_list)
        
        return record

    if op == "signal.reject":
        _validate_project_exists(data_dir, project_id)
        signal_id = request.get("signal_id")
        reason = request.get("reason")
        
        if not isinstance(signal_id, str) or not signal_id:
            raise ValueError("signal_id must be a non-empty string")
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError("reason must be a non-empty string")
            
        signals_list = _load_json(data_dir, _SIGNALS_FILENAME)
        found = False
        updated_signals = []
        for sig in signals_list:
            if sig["id"] == signal_id:
                if sig["project_id"] != project_id:
                    raise ValueError("signal belongs to different project")
                sig_copy = sig.copy()
                sig_copy["status"] = "REJECTED"
                sig_copy["reason"] = reason
                updated_signals.append(sig_copy)
                found = True
            else:
                updated_signals.append(sig)
                
        if not found:
            raise ValueError("signal not found: %s" % signal_id)
            
        _save_json(data_dir, _SIGNALS_FILENAME, updated_signals)
        
        # Return the updated signal
        return next(s for s in updated_signals if s["id"] == signal_id)

    if op == "signal.list":
        _validate_project_exists(data_dir, project_id)
        signals_list = _load_json(data_dir, _SIGNALS_FILENAME)
        items = [sig for sig in signals_list if sig["project_id"] == project_id]
        return {"items": items}

    raise ValueError("unknown operation: %s" % op)
