"""Milestone M7: Local Publish and earliest usable GUI.

Provides persistent, idempotent local publication operations (send, get, list, reconcile, retry)
with a real threaded HTTP test platform in promotion_publish.py.
Reuses M1 project isolation, M5 content structures, and M6 approval status.
"""

import hashlib
import json
import os
import uuid
import time
import threading
import urllib.request
import urllib.parse
import urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

MILESTONE_ID = "M7"

_PROJECTS_FILENAME = "projects.json"
_CONTENT_FILENAME = "content.json"
_RECEIPTS_FILENAME = "receipts.json"
_PUBLICATIONS_FILENAME = "publications.json"
_METRICS_FILENAME = "metrics.json"
_MEDIA_FILENAME = "media.json"

# Per-data_dir locks to serialize read-modify-write cycles on the shared JSON
# stores. Without this, concurrent publish.send calls each load the receipts
# list, append their own receipt, and save, so the last writer wins and the
# other receipts are lost -> "receipt not found" on later publish.get.
_LOCKS = {}
_LOCKS_GUARD = threading.Lock()


def _lock_for(data_dir):
    key = os.path.abspath(data_dir)
    with _LOCKS_GUARD:
        lock = _LOCKS.get(key)
        if lock is None:
            lock = threading.RLock()
            _LOCKS[key] = lock
        return lock


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
    # Use a unique temp file per write to avoid collisions between concurrent
    # writers (e.g. the threaded platform server and the API module) that would
    # otherwise share the same ".tmp" path and cause WinError 32 on replace.
    tmp_path = path + "." + uuid.uuid4().hex + ".tmp"
    try:
        # Ensure we write exactly one valid JSON document to the temp file
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(items, f, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        # Atomic replace ensures no partial writes or concatenated JSON objects remain.
        # Retry with backoff to tolerate transient locks (e.g. antivirus/indexer or
        # another handle briefly holding the destination on Windows).
        last_error = None
        for attempt in range(10):
            try:
                os.replace(tmp_path, path)
                last_error = None
                break
            except PermissionError as exc:
                last_error = exc
                time.sleep(0.01 * (attempt + 1))
        if last_error is not None:
            raise last_error
    finally:
        # Guarantee the temp file handle is closed and the temp file removed if
        # the replace never succeeded, so no stale locks remain.
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass


def _require_project(data_dir, project_id):
    if not isinstance(project_id, str) or not project_id:
        raise ValueError("project_id must be a non-empty string")
    for record in _load_list(data_dir, _PROJECTS_FILENAME):
        if record.get("id") == project_id:
            return record
    raise ValueError("project not found: %s" % project_id)


def _find_content(content_items, project_id, content_id):
    if not isinstance(content_id, str) or not content_id:
        raise ValueError("content_id must be a non-empty string")
    for record in content_items:
        if record.get("id") == content_id:
            if record.get("project_id") != project_id:
                raise ValueError("content not found: %s" % content_id)
            return record
    raise ValueError("content not found: %s" % content_id)


def _validate_approval_status(data_dir, project_id, content_id):
    # Check if content is APPROVED via M6 logic (simplified check on content status field)
    # In the provided M6 code, approval updates content['status'] to 'APPROVED'
    content_items = _load_list(data_dir, _CONTENT_FILENAME)
    record = _find_content(content_items, project_id, content_id)
    if record.get("status") != "APPROVED":
        raise ValueError("content not approved: %s" % content_id)
    return record


def _get_receipt(receipts, receipt_id):
    for r in receipts:
        if r["id"] == receipt_id:
            return r
    return None


def _make_attempt(operation, status, started_at=None, ended_at=None):
    if started_at is None:
        started_at = time.time()
    if ended_at is None:
        ended_at = time.time()
    return {
        "operation": operation,
        "status": status,
        "started_at": started_at,
        "ended_at": ended_at
    }


def _public_receipt(record):
    """Ensure all mandatory fields are present in the returned receipt structure."""
    return {
        "id": record.get("id"),
        "project_id": record.get("project_id"),
        "content_id": record.get("content_id"),
        "revision": record.get("revision"),
        "channel": record.get("channel"),
        "text": record.get("text"),
        "status": record.get("status"),
        "remote_id": record.get("remote_id"),
        "idempotency_key": record.get("idempotency_key"),
        "request_ref": record.get("request_ref"),
        "response_ref": record.get("response_ref"),
        "attempts": record.get("attempts", []),
        "url": record.get("url")
    }


def _do_send(data_dir, project_id, content_id, platform_url, idempotency_key):
    """Perform a publish.send. Caller must hold the data_dir lock."""
    if not isinstance(platform_url, str) or not platform_url:
        raise ValueError("platform_url must be a non-empty string")
    if not isinstance(idempotency_key, str) or not idempotency_key:
        raise ValueError("idempotency_key must be a non-empty string")

    # Validate content and approval
    content_record = _validate_approval_status(data_dir, project_id, content_id)

    # M11 media validation: every referenced media_id must exist and be VALID.
    # Missing or BROKEN media blocks publication with ValueError before any
    # network effects or receipt creation. Validity is re-checked against the
    # stored SHA-256 by hashing the current bytes on disk, so media that was
    # modified or deleted after import is detected as BROKEN here.
    media_ids = content_record.get("media_ids") or []
    if media_ids:
        media_items = _load_list(data_dir, _MEDIA_FILENAME)
        for media_id in media_ids:
            found = None
            for m in media_items:
                if m.get("id") == media_id:
                    found = m
                    break
            if found is None:
                raise ValueError("media not found: %s" % media_id)
            if found.get("project_id") != project_id:
                raise ValueError("media not found: %s" % media_id)
            if found.get("status") == "BROKEN":
                raise ValueError("media is BROKEN: %s" % media_id)
            stored_sha = found.get("sha256")
            stored_path = found.get("path") or found.get("stored_path")
            if stored_sha and stored_path:
                if not os.path.isabs(stored_path):
                    stored_path = os.path.join(data_dir, stored_path)
                if not os.path.exists(stored_path):
                    raise ValueError("media is BROKEN: %s" % media_id)
                try:
                    with open(stored_path, "rb") as mf:
                        current_bytes = mf.read()
                except OSError:
                    raise ValueError("media is BROKEN: %s" % media_id)
                if hashlib.sha256(current_bytes).hexdigest() != stored_sha:
                    raise ValueError("media is BROKEN: %s" % media_id)

    # Acquire the data_dir lock for the entire idempotency check and receipt
    # creation. This prevents concurrent identical keys from both passing the
    # existence check before either receipt is persisted.
    with _lock_for(data_dir):
        receipts = _load_list(data_dir, _RECEIPTS_FILENAME)

        # Idempotency check
        existing_receipt = None
        for r in receipts:
            if r.get("idempotency_key") == idempotency_key:
                existing_receipt = r
                break

        if existing_receipt:
            # If key exists, check if payload matches
            if existing_receipt.get("content_id") != content_id or existing_receipt.get("revision") != content_record.get("revision"):
                raise ValueError("idempotency conflict: key reused with different payload")
            # Return existing receipt without sending again
            return _public_receipt(existing_receipt)

        # Create new receipt
        receipt_id = uuid.uuid4().hex
        receipt = {
            "id": receipt_id,
            "project_id": project_id,
            "content_id": content_id,
            "revision": content_record.get("revision"),
            "channel": content_record.get("channel"),
            "text": content_record.get("text"),
            "status": "PENDING",
            "remote_id": None,
            "idempotency_key": idempotency_key,
            "request_ref": None,
            "response_ref": None,
            "attempts": [],
            "url": None
        }

        # Persist the PENDING receipt immediately so concurrent identical keys
        # see it and return the same receipt instead of sending a second POST.
        receipts.append(receipt)
        _save_list(data_dir, _RECEIPTS_FILENAME, receipts)

    # Prepare POST payload
    payload = {
        "idempotency_key": idempotency_key,
        "project_id": project_id,
        "content_id": content_id,
        "revision": content_record.get("revision"),
        "channel": content_record.get("channel"),
        "text": content_record.get("text")
    }

    url = platform_url.rstrip('/') + '/publish'
    req_data = json.dumps(payload).encode('utf-8')
    req = urllib.request.Request(url, data=req_data, headers={'Content-Type': 'application/json'})

    # Set request_ref to the URL being called
    receipt["request_ref"] = url

    attempt_start = time.time()
    try:
        response = urllib.request.urlopen(req, timeout=10)
        resp_code = response.getcode()
        resp_body = response.read().decode('utf-8')
        attempt_end = time.time()

        if resp_code == 200:
            resp_json = json.loads(resp_body)
            receipt["status"] = "PUBLISHED"
            remote_id = resp_json.get("remote_id", resp_json.get("id"))
            if remote_id is None:
                raise ValueError("platform response missing remote_id")
            receipt["remote_id"] = remote_id
            receipt["url"] = resp_json.get("url")
            receipt["response_ref"] = resp_body
            receipt["attempts"].append(_make_attempt("POST", "SUCCESS", attempt_start, attempt_end))
        else:
            # Unexpected success code treated as failure/unknown? Spec says 200 yields PUBLISHED.
            # If not 200 but no exception, it's weird. Usually urlopen raises for 4xx/5xx.
            receipt["status"] = "FAILED"
            receipt["attempts"].append(_make_attempt("POST", "ERROR", attempt_start, attempt_end))

    except urllib.error.HTTPError as e:
        attempt_end = time.time()
        if e.code == 429:
            receipt["status"] = "RATE_LIMITED"
            receipt["attempts"].append(_make_attempt("POST", "RATE_LIMITED", attempt_start, attempt_end))
        else:
            receipt["status"] = "FAILED"
            receipt["attempts"].append(_make_attempt("POST", "HTTP_ERROR_%d" % e.code, attempt_start, attempt_end))
    except Exception:
        attempt_end = time.time()
        receipt["status"] = "UNKNOWN"
        receipt["attempts"].append(_make_attempt("POST", "TIMEOUT_OR_CONNECTION_LOSS", attempt_start, attempt_end))

    # Persist the final receipt state. Re-load right before persisting so we
    # never clobber receipts written by another process/thread that does not
    # share our in-process lock.
    with _lock_for(data_dir):
        receipts = _load_list(data_dir, _RECEIPTS_FILENAME)
        for i, r in enumerate(receipts):
            if r.get("id") == receipt_id:
                receipts[i] = receipt
                break
        else:
            receipts.append(receipt)
        _save_list(data_dir, _RECEIPTS_FILENAME, receipts)
    return _public_receipt(receipt)


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

    lock = _lock_for(data_dir)

    if op == "publish.send":
        content_id = request.get("content_id")
        platform_url = request.get("platform_url")
        idempotency_key = request.get("idempotency_key")
        # Do NOT hold the data_dir lock across the network POST: independent
        # publications must be able to overlap in time. _do_send performs the
        # HTTP request outside the lock and only takes the lock for the short
        # read-modify-write of the receipts store.
        return _do_send(data_dir, project_id, content_id, platform_url, idempotency_key)

    if op == "publish.get":
        receipt_id = request.get("receipt_id")
        if not isinstance(receipt_id, str) or not receipt_id:
            raise ValueError("receipt_id must be a non-empty string")

        with lock:
            receipts = _load_list(data_dir, _RECEIPTS_FILENAME)
            target = _get_receipt(receipts, receipt_id)
            if not target:
                raise ValueError("receipt not found: %s" % receipt_id)
            if target["project_id"] != project_id:
                raise ValueError("receipt belongs to different project")
            return _public_receipt(target)

    if op == "publish.list":
        with lock:
            receipts = _load_list(data_dir, _RECEIPTS_FILENAME)
            items = [_public_receipt(r) for r in receipts if r["project_id"] == project_id]
            return {"items": items}

    if op == "publish.reconcile":
        receipt_id = request.get("receipt_id")
        platform_url = request.get("platform_url")

        if not isinstance(receipt_id, str) or not receipt_id:
            raise ValueError("receipt_id must be a non-empty string")
        if not isinstance(platform_url, str) or not platform_url:
            raise ValueError("platform_url must be a non-empty string")

        with lock:
            receipts = _load_list(data_dir, _RECEIPTS_FILENAME)
            target = _get_receipt(receipts, receipt_id)
            if not target:
                raise ValueError("receipt not found: %s" % receipt_id)
            if target["project_id"] != project_id:
                raise ValueError("receipt belongs to different project")

            idempotency_key = target["idempotency_key"]
            url = platform_url.rstrip('/') + '/publications?key=' + urllib.parse.quote(idempotency_key)

            # Update request_ref for this operation
            target["request_ref"] = url

            attempt_start = time.time()
            try:
                req = urllib.request.Request(url)
                response = urllib.request.urlopen(req, timeout=10)
                resp_code = response.getcode()
                resp_body = response.read().decode('utf-8')
                attempt_end = time.time()

                if resp_code == 200:
                    resp_json = json.loads(resp_body)
                    # Confirm published
                    target["status"] = "PUBLISHED"
                    target["remote_id"] = resp_json.get("id")
                    target["url"] = resp_json.get("url")
                    target["response_ref"] = resp_body
                    target["attempts"].append(_make_attempt("GET_RECONCILE", "CONFIRMED", attempt_start, attempt_end))
                elif resp_code == 404:
                    # Absent
                    target["status"] = "ABSENT"
                    target["response_ref"] = resp_body
                    target["attempts"].append(_make_attempt("GET_RECONCILE", "ABSENT", attempt_start, attempt_end))
                else:
                    target["response_ref"] = resp_body
                    target["attempts"].append(_make_attempt("GET_RECONCILE", "UNEXPECTED_CODE_%d" % resp_code, attempt_start, attempt_end))

            except urllib.error.HTTPError as e:
                attempt_end = time.time()
                if e.code == 404:
                    target["status"] = "ABSENT"
                    target["attempts"].append(_make_attempt("GET_RECONCILE", "ABSENT", attempt_start, attempt_end))
                else:
                    target["attempts"].append(_make_attempt("GET_RECONCILE", "HTTP_ERROR_%d" % e.code, attempt_start, attempt_end))
            except Exception:
                attempt_end = time.time()
                target["attempts"].append(_make_attempt("GET_RECONCILE", "NETWORK_ERROR", attempt_start, attempt_end))

            _save_list(data_dir, _RECEIPTS_FILENAME, receipts)
            return _public_receipt(target)

    if op == "publish.retry":
        receipt_id = request.get("receipt_id")
        platform_url = request.get("platform_url")

        if not isinstance(receipt_id, str) or not receipt_id:
            raise ValueError("receipt_id must be a non-empty string")
        if not isinstance(platform_url, str) or not platform_url:
            raise ValueError("platform_url must be a non-empty string")

        with lock:
            receipts = _load_list(data_dir, _RECEIPTS_FILENAME)
            target = _get_receipt(receipts, receipt_id)
            if not target:
                raise ValueError("receipt not found: %s" % receipt_id)
            if target["project_id"] != project_id:
                raise ValueError("receipt belongs to different project")

            # Only retry failed branches (RATE_LIMITED, FAILED, UNKNOWN, ABSENT?)
            # Spec: "re-sends only failed branches". Successful siblings untouched.
            # Here we assume single branch per receipt for simplicity unless structure implies otherwise.
            # If status is PUBLISHED, do nothing?
            if target["status"] == "PUBLISHED":
                return _public_receipt(target)

            # Re-send using same idempotency key
            content_id = target["content_id"]
            idempotency_key = target["idempotency_key"]

            # Fetch current content state to ensure revision hasn't changed unexpectedly?
            # Or use stored revision? Spec says "Reusing a key with changed revision/payload is rejected" in send.
            # For retry, we are re-sending the *original* intent.
            # However, if the content was edited after failure, should we send old or new?
            # "publish.retry re-sends only failed branches." Implies resending the original request.
            # We will reconstruct payload from receipt fields.

            payload = {
                "idempotency_key": idempotency_key,
                "project_id": project_id,
                "content_id": content_id,
                "revision": target["revision"],
                "channel": target["channel"],
                "text": target["text"]
            }

            url = platform_url.rstrip('/') + '/publish'
            req_data = json.dumps(payload).encode('utf-8')
            req = urllib.request.Request(url, data=req_data, headers={'Content-Type': 'application/json'})

            # Update request_ref for this operation
            target["request_ref"] = url

            attempt_start = time.time()
            try:
                response = urllib.request.urlopen(req, timeout=10)
                resp_code = response.getcode()
                resp_body = response.read().decode('utf-8')
                attempt_end = time.time()

                if resp_code == 200:
                    resp_json = json.loads(resp_body)
                    target["status"] = "PUBLISHED"
                    target["remote_id"] = resp_json.get("remote_id", resp_json.get("id"))
                    target["url"] = resp_json.get("url")
                    target["response_ref"] = resp_body
                    target["attempts"].append(_make_attempt("POST_RETRY", "SUCCESS", attempt_start, attempt_end))
                else:
                    target["status"] = "FAILED"
                    target["response_ref"] = resp_body
                    target["attempts"].append(_make_attempt("POST_RETRY", "ERROR", attempt_start, attempt_end))

            except urllib.error.HTTPError as e:
                attempt_end = time.time()
                if e.code == 429:
                    target["status"] = "RATE_LIMITED"
                    target["attempts"].append(_make_attempt("POST_RETRY", "RATE_LIMITED", attempt_start, attempt_end))
                else:
                    target["status"] = "FAILED"
                    target["attempts"].append(_make_attempt("POST_RETRY", "HTTP_ERROR_%d" % e.code, attempt_start, attempt_end))
            except Exception:
                attempt_end = time.time()
                target["status"] = "UNKNOWN"
                target["attempts"].append(_make_attempt("POST_RETRY", "TIMEOUT_OR_CONNECTION_LOSS", attempt_start, attempt_end))

            _save_list(data_dir, _RECEIPTS_FILENAME, receipts)
            return _public_receipt(target)

    raise ValueError("unknown operation: %s" % op)


class PlatformHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def _read_json(self):
        length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(length)
        return json.loads(body.decode('utf-8'))

    def _send_json(self, code, data):
        self.send_response(code)
        self.send_header('Content-type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps(data).encode('utf-8'))

    def do_POST(self):
        if self.path == '/publish':
            try:
                payload = self._read_json()
                idem_key = payload.get('idempotency_key')
                if not idem_key:
                    self._send_json(400, {"error": "missing idempotency_key"})
                    return

                lock = _lock_for(self.server.data_dir)
                with lock:
                    # Load publications store
                    pubs = _load_list(self.server.data_dir, _PUBLICATIONS_FILENAME)

                    # Check idempotency
                    for pub in pubs:
                        if pub.get('idempotency_key') == idem_key:
                            # Already processed
                            self._send_json(200, {"id": pub['id'], "url": pub['url'], "remote_id": pub['id']})
                            return

                    # Create new publication
                    pub_id = uuid.uuid4().hex
                    url = "http://localhost:%d/publications/%s" % (self.server.port, pub_id)
                    new_pub = {
                        "id": pub_id,
                        "idempotency_key": idem_key,
                        "project_id": payload.get('project_id'),
                        "content_id": payload.get('content_id'),
                        "revision": payload.get('revision'),
                        "channel": payload.get('channel'),
                        "text": payload.get('text'),
                        "url": url
                    }
                    pubs.append(new_pub)
                    _save_list(self.server.data_dir, _PUBLICATIONS_FILENAME, pubs)

                    # Update metrics
                    metrics = _load_list(self.server.data_dir, _METRICS_FILENAME)
                    metric_entry = {
                        "remote_id": pub_id,
                        "count": 1,
                        "views": 0,
                        "impressions": 0,
                        "reactions": 0,
                        "comments": 0
                    }
                    found = False
                    for m in metrics:
                        if m["remote_id"] == pub_id:
                            m["count"] += 1
                            found = True
                            break
                    if not found:
                        metrics.append(metric_entry)
                    _save_list(self.server.data_dir, _METRICS_FILENAME, metrics)

                self._send_json(200, {"id": pub_id, "url": url, "remote_id": pub_id})

            except Exception as e:
                self._send_json(500, {"error": str(e)})
        else:
            self._send_json(404, {"error": "not found"})

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == '/publications':
            params = urllib.parse.parse_qs(parsed.query)
            key = params.get('key', [None])[0]
            if not key:
                self._send_json(400, {"error": "missing key"})
                return

            lock = _lock_for(self.server.data_dir)
            with lock:
                pubs = _load_list(self.server.data_dir, _PUBLICATIONS_FILENAME)
                for pub in pubs:
                    if pub.get('idempotency_key') == key:
                        self._send_json(200, {"id": pub['id'], "remote_id": pub['id'], "url": pub['url']})
                        return
            self._send_json(404, {"error": "not found"})

        elif parsed.path == '/metrics':
            params = urllib.parse.parse_qs(parsed.query)
            remote_id = params.get('remote_id', [None])[0]
            if not remote_id:
                self._send_json(400, {"error": "missing remote_id"})
                return

            lock = _lock_for(self.server.data_dir)
            with lock:
                metrics = _load_list(self.server.data_dir, _METRICS_FILENAME)
                for m in metrics:
                    if m["remote_id"] == remote_id:
                        self._send_json(200, {
                            "remote_id": remote_id,
                            "count": m.get("count", 1),
                            "views": m.get("views", 0),
                            "impressions": m.get("impressions", 0),
                            "reactions": m.get("reactions", 0),
                            "comments": m.get("comments", 0)
                        })
                        return
            self._send_json(404, {"error": "not found"})
        else:
            self._send_json(404, {"error": "not found"})


def serve_platform(host, port, data_dir):
    server = ThreadingHTTPServer((host, port), PlatformHandler)
    server.data_dir = data_dir
    server.port = port
    print("Platform serving on %s:%d" % (host, port))
    server.serve_forever()
