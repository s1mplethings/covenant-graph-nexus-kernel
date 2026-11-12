"""Milestone M11: Media.

Provides persistent, project-isolated media import, retrieval and listing with
signature validation, integrity checking, and integration into approval/publication
workflows to block broken media.

Operations: media.import, media.get, media.list.
"""

import hashlib
import json
import os
import uuid

MILESTONE_ID = "M11"

_PROJECTS_FILENAME = "projects.json"
_MEDIA_FILENAME = "media.json"
_MEDIA_DIR_NAME = "media_storage"

# Signature definitions for supported media types
_SIGNATURES = {
    "image": [
        b"\x89PNG\r\n\x1a\n",  # PNG
        b"\xff\xd8\xff",       # JPEG
    ],
    "video": [
        b"\x1a\x45\xdf\xa3",   # WebM/Matroska
        b"ftypisom",           # MP4 (ISO Base Media)
        b"ftypmp4",            # MP4
        b"ftypM4A",            # MP4 Audio
        b"ftypM4V",            # MP4 Video
    ],
}


def _path(data_dir, filename):
    return os.path.join(data_dir, filename)


def _load_list(data_dir, filename):
    path = _path(data_dir, filename)
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


def _save_list(data_dir, filename, items):
    os.makedirs(data_dir, exist_ok=True)
    path = _path(data_dir, filename)
    tmp_path = path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False)
    os.replace(tmp_path, path)


def _require_project(data_dir, project_id):
    if not isinstance(project_id, str) or not project_id:
        raise ValueError("project_id must be a non-empty string")
    for record in _load_list(data_dir, _PROJECTS_FILENAME):
        if record.get("id") == project_id:
            return record
    raise ValueError("project not found: %s" % project_id)


def _validate_signature(file_bytes, kind):
    """Check if file bytes match the expected signature for the declared kind."""
    if kind not in _SIGNATURES:
        raise ValueError("unsupported media kind: %s" % kind)
    
    signatures = _SIGNATURES[kind]
    for sig in signatures:
        if file_bytes.startswith(sig):
            return True
    
    # Special handling for MP4 which might have 'ftyp' at offset 4
    if kind == "video":
        if len(file_bytes) >= 12 and file_bytes[4:8] == b"ftyp":
            return True
            
    return False


def _compute_sha256(file_bytes):
    return hashlib.sha256(file_bytes).hexdigest()


def _get_media_storage_dir(data_dir, project_id):
    """Get the directory for storing media files for a specific project."""
    storage_dir = os.path.join(data_dir, _MEDIA_DIR_NAME, project_id)
    os.makedirs(storage_dir, exist_ok=True)
    return storage_dir


def _verify_integrity(data_dir, record):
    """Verify that stored bytes match recorded SHA-256. Update status if needed."""
    media_id = record["id"]
    project_id = record["project_id"]
    expected_sha = record["sha256"]
    relative_path = record["path"]
    
    full_path = os.path.join(data_dir, relative_path)
    
    if not os.path.exists(full_path):
        record["status"] = "BROKEN"
        return False
        
    try:
        with open(full_path, "rb") as f:
            actual_bytes = f.read()
        actual_sha = _compute_sha256(actual_bytes)
        if actual_sha != expected_sha:
            record["status"] = "BROKEN"
            return False
    except Exception:
        record["status"] = "BROKEN"
        return False
        
    record["status"] = "VALID"
    return True


def _public_media(record, data_dir=None):
    public_path = record["path"]
    if data_dir is not None:
        public_path = os.path.abspath(os.path.join(data_dir, record["path"]))
    return {
        "id": record["id"],
        "project_id": record["project_id"],
        "kind": record["kind"],
        "sha256": record["sha256"],
        "path": public_path,
        "status": record["status"],
    }


def handle(data_dir, request):
    if not isinstance(data_dir, str) or not data_dir:
        raise ValueError("data_dir must be a non-empty string")
    if not isinstance(request, dict):
        raise ValueError("request must be a dict")

    op = request.get("op")
    if not isinstance(op, str) or not op:
        raise ValueError("request must contain a non-empty 'op' string")

    project_id = request.get("project_id")
    _require_project(data_dir, project_id)

    if op == "media.import":
        source_path = request.get("path")
        if not isinstance(source_path, str) or not source_path:
            raise ValueError("path must be a non-empty string")
            
        kind = request.get("kind")
        if not isinstance(kind, str) or not kind:
            raise ValueError("kind must be a non-empty string")
            
        if kind not in _SIGNATURES:
            raise ValueError("unsupported media kind: %s" % kind)

        # Read source file
        if not os.path.exists(source_path):
            raise ValueError("source file not found: %s" % source_path)
            
        try:
            with open(source_path, "rb") as f:
                file_bytes = f.read()
        except Exception as e:
            raise ValueError("cannot read source file: %s" % str(e))
            
        if not file_bytes:
            raise ValueError("file is empty")
            
        # Validate signature
        if not _validate_signature(file_bytes, kind):
            raise ValueError("file signature does not match declared kind: %s" % kind)
            
        # Compute hash from source bytes
        sha256 = _compute_sha256(file_bytes)
        
        # Generate ID and storage path
        media_id = uuid.uuid4().hex
        storage_dir = _get_media_storage_dir(data_dir, project_id)
        
        # Determine extension based on kind/signature? Just use generic or original?
        # Contract says "relative storage location". Let's use id + ext from source or kind.
        _, ext = os.path.splitext(source_path)
        if not ext:
            ext = ".bin"
        
        filename = "%s%s" % (media_id, ext)
        dest_path = os.path.join(storage_dir, filename)
        relative_dest = os.path.relpath(dest_path, data_dir)
        absolute_dest = os.path.abspath(dest_path)
        
        # Copy bytes to project-owned storage atomically
        tmp_dest_path = dest_path + ".tmp"
        try:
            with open(tmp_dest_path, "wb") as f:
                f.write(file_bytes)
            os.replace(tmp_dest_path, dest_path)
        except Exception as e:
            # Clean up temp file if it exists
            if os.path.exists(tmp_dest_path):
                try:
                    os.remove(tmp_dest_path)
                except OSError:
                    pass
            raise ValueError("failed to copy media to storage: %s" % str(e))
            
        # Verify written bytes match expected hash
        try:
            with open(dest_path, "rb") as f:
                written_bytes = f.read()
            written_sha = _compute_sha256(written_bytes)
            if written_sha != sha256:
                raise ValueError("integrity check failed after write")
        except Exception as e:
            # If verification fails, remove the corrupted file
            if os.path.exists(dest_path):
                try:
                    os.remove(dest_path)
                except OSError:
                    pass
            raise ValueError("failed to verify media integrity: %s" % str(e))
            
        # Create record
        record = {
            "id": media_id,
            "project_id": project_id,
            "kind": kind,
            "sha256": sha256,
            "path": relative_dest,
            "status": "VALID",
        }
        
        # Persist metadata
        media_items = _load_list(data_dir, _MEDIA_FILENAME)
        media_items.append(record)
        _save_list(data_dir, _MEDIA_FILENAME, media_items)
        
        return _public_media(record)

    if op == "media.get":
        media_id = request.get("media_id")
        if not isinstance(media_id, str) or not media_id:
            raise ValueError("media_id must be a non-empty string")
            
        media_items = _load_list(data_dir, _MEDIA_FILENAME)
        target_record = None
        for r in media_items:
            if r["id"] == media_id:
                if r["project_id"] != project_id:
                    raise ValueError("media not found: %s" % media_id)
                target_record = r
                break
                
        if not target_record:
            raise ValueError("media not found: %s" % media_id)
            
        # Verify integrity
        _verify_integrity(data_dir, target_record)
        
        # Save updated status if changed
        _save_list(data_dir, _MEDIA_FILENAME, media_items)
        
        return _public_media(target_record)

    if op == "media.list":
        media_items = _load_list(data_dir, _MEDIA_FILENAME)
        items = []
        changed = False
        for r in media_items:
            if r["project_id"] != project_id:
                continue
            # Verify integrity for each item
            old_status = r["status"]
            _verify_integrity(data_dir, r)
            if r["status"] != old_status:
                changed = True
            items.append(_public_media(r))
            
        if changed:
            _save_list(data_dir, _MEDIA_FILENAME, media_items)
            
        return {"items": items}

    raise ValueError("unknown operation: %s" % op)
