"""Milestone M10: Analytics and evidence reuse.

Provides persistent, project-isolated analytics operations over M7 publication
receipts. Reuses M1 project isolation and the authoritative M7 receipt store
(receipts.json written by promotion_publish). Metrics are fetched from a local
platform_url via an actual HTTP GET to '/metrics?remote_id=...', validated for
structure/remote_id match/non-negative values, and retained as separate samples.

Operations: analytics.fetch, analytics.history, analytics.recommend.
"""

import json
import os
import uuid
from datetime import datetime, timezone

MILESTONE_ID = "M10"

_PROJECTS_FILENAME = "projects.json"
_RECEIPTS_FILENAME = "receipts.json"
_ANALYTICS_FILENAME = "analytics_samples.json"

_METRIC_FIELDS = ("views", "impressions", "reactions", "comments")


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
    tmp_path = path + "." + uuid.uuid4().hex + ".tmp"
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(items, f, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
    finally:
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


def _find_receipt(data_dir, project_id, receipt_id):
    if not isinstance(receipt_id, str) or not receipt_id:
        raise ValueError("receipt_id must be a non-empty string")
    for record in _load_list(data_dir, _RECEIPTS_FILENAME):
        if record.get("id") == receipt_id:
            if record.get("project_id") != project_id:
                raise ValueError("receipt not found: %s" % receipt_id)
            return record
    raise ValueError("receipt not found: %s" % receipt_id)


def _validate_platform_url(platform_url):
    if not isinstance(platform_url, str) or not platform_url.strip():
        raise ValueError("platform_url must be a non-empty string")
    return platform_url.strip()


def _fetch_metrics(platform_url, remote_id):
    """Perform an actual GET to platform_url+'/metrics?remote_id='+remote_id."""
    import urllib.request
    import urllib.parse
    import urllib.error

    url = platform_url.rstrip('/') + '/metrics?remote_id=' + urllib.parse.quote(str(remote_id))
    req = urllib.request.Request(url)
    try:
        response = urllib.request.urlopen(req, timeout=10)
    except Exception as exc:
        raise ValueError("network error fetching metrics: %s" % exc)
    code = response.getcode()
    body = response.read().decode('utf-8')
    if code != 200:
        raise ValueError("unexpected metrics response code: %s" % code)
    try:
        data = json.loads(body)
    except (ValueError, TypeError):
        raise ValueError("malformed metrics response body")
    if not isinstance(data, dict):
        raise ValueError("malformed metrics response structure")
    returned_remote_id = data.get("remote_id")
    if returned_remote_id != remote_id:
        raise ValueError(
            "remote_id mismatch: expected %s got %s" % (remote_id, returned_remote_id)
        )
    metrics = {}
    for field in _METRIC_FIELDS:
        value = data.get(field)
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError("malformed metric value for %s" % field)
        if value < 0:
            raise ValueError("negative metric value for %s" % field)
        metrics[field] = value
    return metrics


def _public_sample(record):
    return {
        "id": record["id"],
        "receipt_id": record["receipt_id"],
        "content_id": record["content_id"],
        "revision": record["revision"],
        "channel": record["channel"],
        "fetched_at": record["fetched_at"],
        "metrics": dict(record["metrics"]),
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

    if op == "analytics.fetch":
        receipt_id = request.get("receipt_id")
        platform_url = _validate_platform_url(request.get("platform_url"))
        receipt = _find_receipt(data_dir, project_id, receipt_id)
        if receipt.get("status") != "PUBLISHED":
            raise ValueError("receipt not published: %s" % receipt_id)
        remote_id = receipt.get("remote_id")
        if not isinstance(remote_id, str) or not remote_id:
            raise ValueError("receipt missing remote_id: %s" % receipt_id)

        metrics = _fetch_metrics(platform_url, remote_id)

        sample = {
            "id": uuid.uuid4().hex,
            "project_id": project_id,
            "receipt_id": receipt_id,
            "content_id": receipt.get("content_id"),
            "revision": receipt.get("revision"),
            "channel": receipt.get("channel"),
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "metrics": metrics,
        }
        samples = _load_list(data_dir, _ANALYTICS_FILENAME)
        samples.append(sample)
        _save_list(data_dir, _ANALYTICS_FILENAME, samples)
        return _public_sample(sample)

    if op == "analytics.history":
        receipt_id = request.get("receipt_id")
        # Validate receipt ownership/project even for history reads.
        _find_receipt(data_dir, project_id, receipt_id)
        samples = _load_list(data_dir, _ANALYTICS_FILENAME)
        items = [
            _public_sample(s)
            for s in samples
            if s.get("project_id") == project_id and s.get("receipt_id") == receipt_id
        ]
        return {"items": items}

    if op == "analytics.recommend":
        samples = _load_list(data_dir, _ANALYTICS_FILENAME)
        project_samples = [s for s in samples if s.get("project_id") == project_id]
        sample_count = len(project_samples)
        confidence = "LOW" if sample_count < 5 else "MODERATE"
        evidence_refs = [s["id"] for s in project_samples]
        reason_summary = (
            "Aggregated %d persisted analytics sample(s); recommendation is based on "
            "actual metrics evidence only." % sample_count
        )
        if sample_count == 0:
            recommendation = "INSUFFICIENT_DATA"
        elif confidence == "LOW":
            recommendation = "GATHER_MORE_SAMPLES"
        else:
            recommendation = "CONTINUE_MONITORING"
        return {
            "sample_count": sample_count,
            "confidence": confidence,
            "evidence_refs": evidence_refs,
            "reason_summary": reason_summary,
            "recommendation": recommendation,
        }

    raise ValueError("unknown operation: %s" % op)
