"""One explicit legacy JSON sender; no retries, no domestic access.

Retained for named legacy experiments, never a domestic failure fallback.
"""
import json,time,urllib.request,urllib.error,ssl
from datetime import datetime,timezone
from typing import Any
from scripts import check_connectivity
from scripts.check_connectivity import _set_last_transport_timing,_http_error_summary,_request_error_summary


def post_json_once(endpoint,payload,token,timeout_sec):
    from .application_network import settings
    if settings():raise RuntimeError('DOMESTIC_LEGACY_POST_REFUSED')
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    started = time.monotonic()
    timing: dict[str, Any] = {
        "request_started_at": datetime.now(timezone.utc).isoformat(),
        "request_body_bytes": len(data),
        "timeout_seconds": int(timeout_sec),
        "response_headers_received": False,
        "response_body_received": False,
    }
    _set_last_transport_timing(timing)
    req = urllib.request.Request(
        endpoint,
        data=data,
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "CGNK-Connectivity/1",
            "Connection": "close",
        },
    )
    response_opened = False
    try:
        with check_connectivity._urlopen(req, timeout_sec) as resp:
            response_opened = True
            timing["response_headers_received"] = True
            timing["response_headers_elapsed_ms"] = round(
                (time.monotonic() - started) * 1000
            )
            timing["response_status"] = int(getattr(resp, "status", 0) or 0)
            body = resp.read().decode("utf-8", errors="replace")
            timing["response_body_received"] = bool(body)
            timing["response_body_bytes"] = len(body.encode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace").strip()
        timing["failure_phase"] = "http_response"
        timing["response_headers_received"] = True
        timing["response_status"] = int(getattr(exc, "code", 0) or 0)
        timing["response_body_received"] = bool(detail)
        timing["response_body_bytes"] = len(detail.encode("utf-8"))
        timing["total_elapsed_ms"] = round((time.monotonic() - started) * 1000)
        _set_last_transport_timing(timing)
        return None, _http_error_summary(exc, endpoint, detail)
    except (urllib.error.URLError, TimeoutError, ConnectionError, ConnectionResetError, ssl.SSLError) as exc:
        timing["failure_phase"] = (
            "response_body" if response_opened else "connect_or_response_headers"
        )
        timing["total_elapsed_ms"] = round((time.monotonic() - started) * 1000)
        _set_last_transport_timing(timing)
        return None, f"request failed: {_request_error_summary(exc, endpoint)}"
    except Exception as exc:
        timing["failure_phase"] = (
            "response_body" if response_opened else "connect_or_response_headers"
        )
        timing["total_elapsed_ms"] = round((time.monotonic() - started) * 1000)
        _set_last_transport_timing(timing)
        return None, f"request failed: {_request_error_summary(exc, endpoint)}"
    timing["total_elapsed_ms"] = round((time.monotonic() - started) * 1000)
    _set_last_transport_timing(timing)
    try:
        doc = json.loads(body)
    except Exception as exc:
        return None, f"non-json response: {exc}"
    if not isinstance(doc, dict):
        return None, "response is not object"
    return doc, ""

