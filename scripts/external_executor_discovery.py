#!/usr/bin/env python3
"""Bounded external-executor discovery for eligible commodity capabilities.

This module is executor-selection support only.  It owns no requirement,
planning, scheduling, Provider, evidence, acceptance, packaging, delivery, or
publication authority.  Every remote result is an untrusted candidate until
deterministic policy and an isolated bounded trial both pass.
"""

from __future__ import annotations

import hashlib
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Iterable, Mapping


SCHEMA_VERSION = "1.0"
USER_AGENT = "CGKN/0.2.0-rc.2"
HTTP_TIMEOUT_SECONDS = 10
MAX_RESPONSE_BYTES = 1_000_000
MAX_QUERIES = 5
MAX_SOURCE_RESULTS = 8
MAX_CANDIDATES = 15
MAX_TRIAL_CANDIDATES = 3
MAX_TRUST_CANDIDATES = 5
TRIAL_TIMEOUT_SECONDS = 90
SECURITY_TTL_SECONDS = 6 * 60 * 60
MAINTENANCE_TTL_SECONDS = 24 * 60 * 60
ALLOWED_HOSTS = {"api.github.com", "pypi.org", "api.deps.dev", "api.osv.dev"}
SECRET_ENV_MARKERS = ("KEY", "TOKEN", "SECRET", "PASSWORD", "CREDENTIAL")

PERMISSIVE_LICENSES = {
    "MIT",
    "BSD-2-CLAUSE",
    "BSD-3-CLAUSE",
    "APACHE-2.0",
    "ISC",
    "PSF-2.0",
}
REVIEW_LICENSE_MARKERS = ("GPL", "AGPL", "LGPL", "MPL", "EPL", "CDDL")
BLOCKED_LICENSES = {"UNLICENSED", "PROPRIETARY-INCOMPATIBLE"}

ELIGIBLE_CAPABILITY_MARKERS = (
    "parse", "parser", "extract", "ocr", "image", "video", "frame",
    "database", "http", "scheduler", "queue", "vector", "search",
    "archive", "compression", "document", "pdf", "spreadsheet", "media",
)
INELIGIBLE_CAPABILITY_MARKERS = (
    "business rule", "customer-specific", "proprietary workflow",
    "domain policy", "tiny glue", "custom approval",
)

# Deterministic package hints seed registry lookups; remote facts still decide.
PACKAGE_HINTS: dict[str, tuple[str, ...]] = {
    "video": ("ffmpeg-python", "av", "imageio-ffmpeg"),
    "frame": ("ffmpeg-python", "av", "imageio-ffmpeg"),
    "ocr": ("pytesseract", "easyocr"),
    "pdf": ("pypdf", "pdfplumber"),
    "http": ("httpx", "requests"),
    "scheduler": ("apscheduler",),
    "queue": ("rq",),
    "vector": ("faiss-cpu",),
}


@dataclass(frozen=True)
class SourceError:
    source: str
    classification: str
    message: str

    def as_dict(self) -> dict[str, str]:
        return {
            "source": self.source,
            "classification": self.classification,
            "message": self.message[:500],
        }


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _bounded_text(value: Any, limit: int = 1000) -> str:
    return str(value or "").strip()[:limit]


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9._-]+", "-", value.lower()).strip("-")[:120]


def _unique(values: Iterable[Any], limit: int) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        item = _bounded_text(value, 200)
        if item and item.lower() not in seen:
            seen.add(item.lower())
            result.append(item)
        if len(result) >= limit:
            break
    return result


def should_discover_external_executor(capability: Mapping[str, Any]) -> bool:
    text = " ".join(
        _bounded_text(capability.get(key), 500)
        for key in ("id", "label", "goal", "reason", "category")
    ).lower()
    if any(marker in text for marker in INELIGIBLE_CAPABILITY_MARKERS):
        return False
    return any(marker in text for marker in ELIGIBLE_CAPABILITY_MARKERS)


def build_search_intent(
    capability: Mapping[str, Any],
    *,
    language: str = "python",
    platform: str | None = None,
    constraints: Iterable[str] = (),
    required_interfaces: Iterable[str] = (),
    max_candidates: int = 8,
) -> dict[str, Any]:
    capability_id = _slug(_bounded_text(capability.get("id") or capability.get("label") or "capability"))
    label = _bounded_text(capability.get("label") or capability.get("goal") or capability_id, 160)
    target_platform = _bounded_text(platform or ("windows" if os.name == "nt" else sys.platform), 40).lower()
    terms = [f"{label} {language}", f"{capability_id.replace('_', ' ')} {language} {target_platform}"]
    interfaces = _unique(required_interfaces, 8)
    terms.extend(f"{label} {item}" for item in interfaces[:2])
    for marker, hints in PACKAGE_HINTS.items():
        if marker in f"{capability_id} {label}".lower():
            terms.extend(f"{hint} {language}" for hint in hints[:2])
            break
    return {
        "kind": "CGKNExternalExecutorSearchIntent",
        "schema_version": SCHEMA_VERSION,
        "capability_id": capability_id,
        "query_terms": _unique(terms, MAX_QUERIES),
        "language": _bounded_text(language, 30).lower(),
        "platform": target_platform,
        "local_first": True,
        "offline_runtime_preferred": True,
        "required_interfaces": interfaces,
        "constraints": _unique(constraints, 12),
        "max_candidates": max(1, min(int(max_candidates), MAX_CANDIDATES)),
    }


def _blank_candidate(
    intent: Mapping[str, Any],
    *,
    name: str,
    candidate_kind: str,
    ecosystem: str,
    package_name: str | None = None,
    repository: str | None = None,
    sources: Iterable[str] = (),
) -> dict[str, Any]:
    identity = f"{ecosystem}:{package_name or repository or name}"
    return {
        "kind": "CGKNExternalExecutorCandidate",
        "schema_version": SCHEMA_VERSION,
        "candidate_id": "candidate." + hashlib.sha256(identity.lower().encode("utf-8")).hexdigest()[:16],
        "capability_id": _bounded_text(intent.get("capability_id"), 120),
        "name": _bounded_text(name, 200),
        "candidate_kind": candidate_kind,
        "ecosystem": ecosystem,
        "package_name": _bounded_text(package_name, 200) or None,
        "repository": _bounded_text(repository, 500) or None,
        "sources": _unique(sources, 8),
        "version": None,
        "latest_release": None,
        "license": {"spdx": None, "status": "UNKNOWN", "policy": "UNKNOWN"},
        "maintenance": {
            "status": "UNKNOWN", "activity": "UNKNOWN", "archived": False,
            "disabled": False, "deprecated": False, "last_push_at": None,
            "latest_release_at": None, "latest_release_tag": None,
            "last_push_age_days": None, "latest_release_age_days": None,
            "has_published_release": None, "sources": [], "reasons": [],
            "evaluated_at": None,
        },
        "popularity": {"stars": None, "downloads": None},
        "security": {
            "status": "UNKNOWN", "exact_version_checked": None,
            "known_advisories": [], "max_severity": None, "affected": None,
            "fixed_versions": [], "patched_version_available": None,
            "sources": [], "reasons": ["exact_version_not_checked"],
            "evaluated_at": None,
        },
        "compatibility": {
            "language": "UNKNOWN", "platform": "UNKNOWN", "runtime": "UNKNOWN",
            "project_constraints": "UNKNOWN",
        },
        "requirement_fit": {"status": "UNKNOWN", "reasons": []},
        "metadata_status": "UNAVAILABLE",
        "runtime_network_required": False,
        "trial": {"status": "NOT_EVALUATED", "command": None, "evidence": []},
    }


def _safe_json_request(
    url: str,
    *,
    source: str,
    method: str = "GET",
    json_body: Mapping[str, Any] | None = None,
    headers: Mapping[str, str] | None = None,
    timeout: int = HTTP_TIMEOUT_SECONDS,
    opener: Callable[..., Any] | None = None,
) -> tuple[Any | None, SourceError | None]:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in ALLOWED_HOSTS:
        return None, SourceError(source, "ENDPOINT_REJECTED", "endpoint is not allowlisted HTTPS")
    request_headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    request_headers.update(dict(headers or {}))
    normalized_method = str(method).upper()
    if normalized_method not in {"GET", "POST"}:
        return None, SourceError(source, "METHOD_REJECTED", "only GET and POST are supported")
    body = None
    if json_body is not None:
        body = json.dumps(dict(json_body), separators=(",", ":")).encode("utf-8")
        request_headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=body, headers=request_headers, method=normalized_method)
    fetch = opener or urllib.request.urlopen
    try:
        with fetch(request, timeout=max(1, min(int(timeout), 15))) as response:
            final = urllib.parse.urlparse(response.geturl())
            if final.scheme != "https" or final.hostname not in ALLOWED_HOSTS:
                return None, SourceError(source, "REDIRECT_REJECTED", "redirect left endpoint allowlist")
            raw = response.read(MAX_RESPONSE_BYTES + 1)
            if len(raw) > MAX_RESPONSE_BYTES:
                return None, SourceError(source, "RESPONSE_TOO_LARGE", "response exceeded byte limit")
            return json.loads(raw.decode("utf-8")), None
    except urllib.error.HTTPError as exc:
        return None, SourceError(source, f"HTTP_{exc.code}", str(exc))
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return None, SourceError(source, "SOURCE_UNAVAILABLE", str(exc))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        return None, SourceError(source, "INVALID_RESPONSE", str(exc))


def _safe_json_get(
    url: str, *, source: str, headers: Mapping[str, str] | None = None,
    timeout: int = HTTP_TIMEOUT_SECONDS, opener: Callable[..., Any] | None = None,
) -> tuple[Any | None, SourceError | None]:
    return _safe_json_request(url, source=source, method="GET", headers=headers, timeout=timeout, opener=opener)


def _parse_timestamp(value: Any) -> datetime | None:
    text = _bounded_text(value, 80)
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None


def _age_days(value: Any, now: datetime) -> int | None:
    parsed = _parse_timestamp(value)
    return max(0, (now - parsed).days) if parsed else None


def parse_github_repository(value: Any) -> tuple[str, str] | None:
    parsed = urllib.parse.urlparse(_bounded_text(value, 500))
    if parsed.scheme != "https" or parsed.hostname != "github.com" or parsed.query or parsed.fragment:
        return None
    parts = [part for part in parsed.path.strip("/").split("/") if part]
    if len(parts) != 2:
        return None
    owner, repo = parts
    repo = repo[:-4] if repo.lower().endswith(".git") else repo
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", owner) or not re.fullmatch(r"[A-Za-z0-9_.-]+", repo):
        return None
    return owner, repo


def _license_policy(spdx: Any, project_policy: Mapping[str, Any] | None = None) -> tuple[str, str]:
    value = _bounded_text(spdx, 100).upper()
    explicitly_blocked = {
        str(item).upper() for item in (project_policy or {}).get("blocked", [])
    }
    if value in explicitly_blocked or value in BLOCKED_LICENSES:
        return "INCOMPATIBLE", "BLOCK"
    if value in PERMISSIVE_LICENSES:
        return "KNOWN", "ALLOW"
    if not value or value in {"NOASSERTION", "OTHER"}:
        return "UNKNOWN", "UNKNOWN"
    if any(marker in value for marker in REVIEW_LICENSE_MARKERS):
        return "KNOWN", "REVIEW"
    return "KNOWN", "REVIEW"


def discover_from_github(
    intent: Mapping[str, Any], *, opener: Callable[..., Any] | None = None
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    candidates: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    per_query = min(MAX_SOURCE_RESULTS, max(1, int(intent.get("max_candidates", 8))))
    for query in list(intent.get("query_terms", []))[:MAX_QUERIES]:
        url = "https://api.github.com/search/repositories?" + urllib.parse.urlencode(
            {"q": query, "sort": "stars", "order": "desc", "per_page": per_query}
        )
        payload, error = _safe_json_get(url, source="github", headers=headers, opener=opener)
        if error:
            errors.append(error.as_dict())
            continue
        for item in (payload or {}).get("items", [])[:per_query]:
            if not isinstance(item, Mapping):
                continue
            repository = _bounded_text(item.get("html_url"), 500)
            candidate = _blank_candidate(
                intent, name=_bounded_text(item.get("full_name"), 200),
                candidate_kind="repository", ecosystem="github", repository=repository,
                sources=("github",),
            )
            spdx = ((item.get("license") or {}).get("spdx_id") if isinstance(item.get("license"), Mapping) else None)
            license_status, policy = _license_policy(spdx)
            candidate.update({
                "description": _bounded_text(item.get("description"), 500),
                "default_branch": _bounded_text(item.get("default_branch"), 100),
                "forks_count": item.get("forks_count"),
            })
            candidate["license"] = {"spdx": spdx, "status": license_status, "policy": policy}
            candidate["maintenance"] = {
                **candidate["maintenance"],
                "archived": bool(item.get("archived")),
                "disabled": bool(item.get("disabled")),
                "last_push_at": item.get("pushed_at"),
                "sources": ["github_search"],
            }
            candidate["popularity"]["stars"] = item.get("stargazers_count")
            language = _bounded_text(item.get("language"), 40).lower()
            required_language = _bounded_text(intent.get("language"), 40).lower()
            candidate["compatibility"]["language"] = "PASS" if not language or language == required_language else "UNKNOWN"
            candidate["compatibility"]["platform"] = "UNKNOWN"
            candidate["requirement_fit"] = {"status": "PARTIAL", "reasons": ["github_keyword_match"]}
            candidate["metadata_status"] = "PARTIAL"
            candidates.append(candidate)
    return merge_candidates(candidates)[:MAX_CANDIDATES], errors


def _hinted_packages(intent: Mapping[str, Any]) -> list[str]:
    text = " ".join([_bounded_text(intent.get("capability_id"), 200), *intent.get("query_terms", [])]).lower()
    packages: list[str] = []
    for marker, hints in PACKAGE_HINTS.items():
        if marker in text:
            packages.extend(hints)
    return _unique(packages, MAX_SOURCE_RESULTS)


def enrich_from_pypi(
    candidate: Mapping[str, Any], *, package_name: str | None = None,
    opener: Callable[..., Any] | None = None,
) -> tuple[dict[str, Any], dict[str, str] | None]:
    result = json.loads(json.dumps(candidate))
    package = _bounded_text(package_name or result.get("package_name"), 200)
    if not package:
        return result, SourceError("pypi", "IDENTIFIER_REQUIRED", "package name is required").as_dict()
    quoted = urllib.parse.quote(package, safe="._-")
    payload, error = _safe_json_get(f"https://pypi.org/pypi/{quoted}/json", source="pypi", opener=opener)
    if error:
        return result, error.as_dict()
    info = (payload or {}).get("info", {})
    if not isinstance(info, Mapping):
        return result, SourceError("pypi", "INVALID_RESPONSE", "info object missing").as_dict()
    result["ecosystem"] = "pypi"
    result["candidate_kind"] = "package"
    result["package_name"] = package
    result["name"] = _bounded_text(info.get("name") or package, 200)
    result["version"] = _bounded_text(info.get("version"), 100) or None
    result["latest_release"] = result["version"]
    result["requires_python"] = _bounded_text(info.get("requires_python"), 200) or None
    project_urls = info.get("project_urls", {}) if isinstance(info.get("project_urls"), Mapping) else {}
    repository = project_urls.get("Source") or project_urls.get("Repository") or project_urls.get("Homepage") or info.get("home_page")
    if repository:
        result["repository"] = _bounded_text(repository, 500)
    classifiers = [str(item) for item in info.get("classifiers", []) if str(item).strip()]
    spdx = _bounded_text(info.get("license"), 100)
    if not spdx:
        license_rows = [item.split(" :: ")[-1] for item in classifiers if item.startswith("License ::")]
        spdx = license_rows[0] if license_rows else ""
    license_status, policy = _license_policy(spdx)
    result["license"] = {"spdx": spdx or None, "status": license_status, "policy": policy}
    result["maintenance"]["deprecated"] = "Development Status :: 7 - Inactive" in classifiers
    result["compatibility"]["language"] = "PASS"
    result["compatibility"]["runtime"] = "PASS" if result["version"] else "UNKNOWN"
    result["requirement_fit"] = {"status": "PARTIAL", "reasons": ["deterministic_package_hint"]}
    result["sources"] = _unique([*result.get("sources", []), "pypi"], 8)
    result["metadata_status"] = "PARTIAL"
    return result, None


def enrich_from_deps_dev(
    candidate: Mapping[str, Any], *, opener: Callable[..., Any] | None = None,
) -> tuple[dict[str, Any], dict[str, str] | None]:
    result = json.loads(json.dumps(candidate))
    package = _bounded_text(result.get("package_name"), 200)
    version = _bounded_text(result.get("version"), 100)
    if not package or not version:
        return result, SourceError("deps.dev", "IDENTIFIER_REQUIRED", "package and version are required").as_dict()
    ecosystem = "pypi" if str(result.get("ecosystem")) == "pypi" else str(result.get("ecosystem", ""))
    url = "https://api.deps.dev/v3/systems/{}/packages/{}/versions/{}".format(
        urllib.parse.quote(ecosystem, safe=""), urllib.parse.quote(package, safe=""), urllib.parse.quote(version, safe="")
    )
    payload, error = _safe_json_get(url, source="deps.dev", opener=opener)
    if error:
        return result, error.as_dict()
    links = (payload or {}).get("links", [])
    for link in links if isinstance(links, list) else []:
        if isinstance(link, Mapping) and str(link.get("label", "")).upper() == "SOURCE_REPO":
            result["repository"] = _bounded_text(link.get("url"), 500)
            break
    licenses = (payload or {}).get("licenses", [])
    spdx = str(licenses[0]) if isinstance(licenses, list) and licenses else result["license"].get("spdx")
    status, policy = _license_policy(spdx)
    result["license"] = {"spdx": spdx or None, "status": status, "policy": policy}
    advisories = [
        _bounded_text(item.get("advisoryKey", {}).get("id"), 200)
        for item in (payload or {}).get("advisoryKeys", [])
        if isinstance(item, Mapping)
    ]
    advisories = [item for item in advisories if item]
    result["security"] = {
        **result["security"],
        "status": "REVIEW" if advisories else "UNKNOWN",
        "known_advisories": advisories,
        "sources": _unique([*result["security"].get("sources", []), "deps.dev"], 8),
        "reasons": (
            ["deps_dev_advisory_requires_exact_version_confirmation"]
            if advisories else ["osv_exact_version_required"]
        ),
    }
    result["sources"] = _unique([*result.get("sources", []), "deps.dev"], 8)
    result["metadata_status"] = "COMPLETE" if status == "KNOWN" and result.get("version") else "PARTIAL"
    return result, None


def evaluate_maintenance(candidate: Mapping[str, Any], *, now: datetime | None = None) -> dict[str, Any]:
    result = json.loads(json.dumps(candidate))
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    maintenance = dict(result.get("maintenance", {}))
    push_age = _age_days(maintenance.get("last_push_at"), current)
    release_age = _age_days(maintenance.get("latest_release_at"), current)
    maintenance["last_push_age_days"] = push_age
    maintenance["latest_release_age_days"] = release_age
    maintenance["evaluated_at"] = current.isoformat()
    if maintenance.get("archived"):
        status, activity, reasons = "BLOCK", "ARCHIVED", ["repository_archived"]
    elif maintenance.get("disabled"):
        status, activity, reasons = "BLOCK", "ARCHIVED", ["repository_disabled"]
    elif maintenance.get("deprecated"):
        status, activity, reasons = "BLOCK", "STALE", ["candidate_deprecated"]
    elif push_age is not None and push_age <= 365:
        status, activity, reasons = "PASS", "ACTIVE", ["recent_repository_push"]
    elif release_age is not None and release_age <= 365:
        status, activity, reasons = "PASS", "ACTIVE", ["recent_published_release"]
    elif push_age is None and release_age is None:
        status, activity, reasons = "UNKNOWN", "UNKNOWN", ["repository_activity_metadata_unavailable"]
    elif (push_age is None or push_age > 730) and (release_age is None or release_age > 730):
        status, activity, reasons = "REVIEW", "STALE", ["repository_activity_stale"]
    else:
        status, activity, reasons = "REVIEW", "STABLE", ["repository_activity_requires_review"]
    maintenance.update({"status": status, "activity": activity, "reasons": reasons})
    result["maintenance"] = maintenance
    return result


def enrich_github_maintenance(
    candidate: Mapping[str, Any], *, now: datetime | None = None,
    opener: Callable[..., Any] | None = None,
) -> tuple[dict[str, Any], list[dict[str, str]]]:
    result = json.loads(json.dumps(candidate))
    identity = parse_github_repository(result.get("repository"))
    if not identity:
        result = evaluate_maintenance(result, now=now)
        result["maintenance"]["reasons"] = ["github_repository_not_applicable"]
        return result, []
    owner, repo = identity
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    errors: list[dict[str, str]] = []
    repo_doc, error = _safe_json_get(
        f"https://api.github.com/repos/{urllib.parse.quote(owner, safe='')}/{urllib.parse.quote(repo, safe='')}",
        source="github_maintenance", headers=headers, opener=opener,
    )
    if error:
        errors.append(error.as_dict())
        return evaluate_maintenance(result, now=now), errors
    maintenance = dict(result["maintenance"])
    maintenance.update({
        "archived": bool((repo_doc or {}).get("archived")),
        "disabled": bool((repo_doc or {}).get("disabled")),
        "last_push_at": (repo_doc or {}).get("pushed_at"),
        "sources": _unique([*maintenance.get("sources", []), "github_repository"], 8),
    })
    release_doc, release_error = _safe_json_get(
        f"https://api.github.com/repos/{urllib.parse.quote(owner, safe='')}/{urllib.parse.quote(repo, safe='')}/releases/latest",
        source="github_release", headers=headers, opener=opener,
    )
    if release_error and release_error.classification == "HTTP_404":
        maintenance["has_published_release"] = False
    elif release_error:
        errors.append(release_error.as_dict())
        maintenance["has_published_release"] = None
    else:
        maintenance.update({
            "has_published_release": True,
            "latest_release_at": (release_doc or {}).get("published_at"),
            "latest_release_tag": _bounded_text((release_doc or {}).get("tag_name"), 100) or None,
            "sources": _unique([*maintenance.get("sources", []), "github_release"], 8),
        })
    result["maintenance"] = maintenance
    return evaluate_maintenance(result, now=now), errors


def normalize_osv_severity(vulnerability: Mapping[str, Any]) -> str:
    explicit: list[str] = []
    database = vulnerability.get("database_specific", {})
    if isinstance(database, Mapping):
        explicit.append(str(database.get("severity", "")))
    for item in vulnerability.get("severity", []) if isinstance(vulnerability.get("severity"), list) else []:
        if isinstance(item, Mapping):
            explicit.extend([str(item.get("score", "")), str(item.get("type", ""))])
    text = " ".join(explicit).upper()
    for label in ("CRITICAL", "HIGH", "MODERATE", "MEDIUM", "LOW"):
        if re.search(rf"\b{label}\b", text):
            return "MEDIUM" if label == "MODERATE" else label
    numeric: list[float] = []
    for value in explicit:
        match = re.fullmatch(r"\s*(10(?:\.0+)?|[0-9](?:\.\d+)?)\s*", value)
        if match:
            numeric.append(float(match.group(1)))
    if not numeric:
        return "UNKNOWN"
    score = max(numeric)
    return "CRITICAL" if score >= 9 else "HIGH" if score >= 7 else "MEDIUM" if score >= 4 else "LOW" if score > 0 else "UNKNOWN"


def _fixed_versions(vulnerabilities: Iterable[Mapping[str, Any]]) -> list[str]:
    values: list[str] = []
    for vulnerability in vulnerabilities:
        for affected in vulnerability.get("affected", []) if isinstance(vulnerability.get("affected"), list) else []:
            if not isinstance(affected, Mapping):
                continue
            for value_range in affected.get("ranges", []) if isinstance(affected.get("ranges"), list) else []:
                if not isinstance(value_range, Mapping):
                    continue
                for event in value_range.get("events", []) if isinstance(value_range.get("events"), list) else []:
                    if isinstance(event, Mapping) and event.get("fixed"):
                        values.append(str(event["fixed"]))
    return _unique(values, 20)


def query_osv_exact_version(
    ecosystem: str, package: str, version: str, *, opener: Callable[..., Any] | None = None,
) -> tuple[dict[str, Any] | None, dict[str, str] | None]:
    mappings = {"pypi": "PyPI", "npm": "npm", "cargo": "crates.io"}
    osv_ecosystem = mappings.get(str(ecosystem).lower())
    if not osv_ecosystem or not package or not version:
        return None, SourceError("osv", "IDENTIFIER_REQUIRED", "supported ecosystem, package, and exact version are required").as_dict()
    payload = {"package": {"ecosystem": osv_ecosystem, "name": package}, "version": version}
    document, error = _safe_json_request(
        "https://api.osv.dev/v1/query", source="osv", method="POST",
        json_body=payload, opener=opener,
    )
    return (document if isinstance(document, dict) else None), (error.as_dict() if error else None)


def enrich_security_from_osv(
    candidate: Mapping[str, Any], *, now: datetime | None = None,
    opener: Callable[..., Any] | None = None,
) -> tuple[dict[str, Any], dict[str, str] | None]:
    result = json.loads(json.dumps(candidate))
    package = _bounded_text(result.get("package_name"), 200)
    version = _bounded_text(result.get("version"), 100)
    evaluated_at = (now or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat()
    deps_advisories = list(result.get("security", {}).get("known_advisories", []))
    if not version:
        result["security"].update({"status": "UNKNOWN", "exact_version_checked": None, "reasons": ["exact_version_required"], "evaluated_at": evaluated_at})
        return result, SourceError("osv", "IDENTIFIER_REQUIRED", "exact version is required").as_dict()
    document, error = query_osv_exact_version(str(result.get("ecosystem", "")), package, version, opener=opener)
    if error:
        result["security"].update({
            "status": "REVIEW" if deps_advisories else "UNKNOWN",
            "exact_version_checked": None,
            "affected": None,
            "reasons": ["deps_dev_advisory_requires_exact_version_confirmation"] if deps_advisories else ["osv_unavailable"],
            "evaluated_at": evaluated_at,
        })
        return result, error
    vulnerabilities = [item for item in (document or {}).get("vulns", []) if isinstance(item, Mapping)]
    advisories = [{
        "id": _bounded_text(item.get("id"), 120),
        "aliases": _unique(item.get("aliases", []), 12),
        "summary": _bounded_text(item.get("summary"), 500),
        "severity": normalize_osv_severity(item),
        "modified": item.get("modified"),
        "published": item.get("published"),
    } for item in vulnerabilities]
    severities = [item["severity"] for item in advisories]
    rank = {"UNKNOWN": 0, "LOW": 1, "MEDIUM": 2, "HIGH": 3, "CRITICAL": 4}
    max_severity = max(severities, key=lambda item: rank[item]) if severities else None
    fixed = _fixed_versions(vulnerabilities)
    if not vulnerabilities:
        status, reasons = "PASS", ["exact_version_no_known_osv_vulnerabilities"]
    elif max_severity in {"CRITICAL", "HIGH"}:
        status, reasons = "BLOCK", ["exact_version_high_severity_vulnerability"]
    else:
        status, reasons = "REVIEW", ["exact_version_vulnerability_requires_review"]
    osv_ids = {item["id"] for item in advisories}
    if deps_advisories and not osv_ids.intersection(deps_advisories):
        status = "REVIEW"
        reasons.append("security_source_conflict")
    result["security"] = {
        "status": status,
        "exact_version_checked": version,
        "known_advisories": advisories,
        "max_severity": max_severity,
        "affected": bool(vulnerabilities),
        "fixed_versions": fixed,
        "patched_version_available": bool(fixed),
        "sources": _unique([*result.get("security", {}).get("sources", []), "osv"], 8),
        "reasons": reasons,
        "evaluated_at": evaluated_at,
    }
    return result, None


def discover_from_registry(
    intent: Mapping[str, Any], *, opener: Callable[..., Any] | None = None
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    if str(intent.get("language", "")).lower() != "python":
        return [], [SourceError("registry", "SOURCE_NOT_APPLICABLE", "v1 implements PyPI for Python").as_dict()]
    candidates: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    for package in _hinted_packages(intent):
        base = _blank_candidate(intent, name=package, candidate_kind="package", ecosystem="pypi", package_name=package, sources=())
        enriched, error = enrich_from_pypi(base, opener=opener)
        if error:
            errors.append(error)
            continue
        enriched, deps_error = enrich_from_deps_dev(enriched, opener=opener)
        if deps_error:
            errors.append(deps_error)
        candidates.append(enriched)
    return candidates[:MAX_SOURCE_RESULTS], errors


def merge_candidates(candidates: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for raw in candidates:
        item = json.loads(json.dumps(raw))
        package = _bounded_text(item.get("package_name"), 200).lower()
        repository = _bounded_text(item.get("repository"), 500).lower().rstrip("/")
        key = f"package:{item.get('ecosystem')}:{package}" if package else f"repo:{repository}" if repository else f"id:{item.get('candidate_id')}"
        if key not in merged:
            merged[key] = item
            continue
        current = merged[key]
        current["sources"] = _unique([*current.get("sources", []), *item.get("sources", [])], 8)
        for field in ("version", "latest_release", "repository"):
            if not current.get(field) and item.get(field):
                current[field] = item[field]
        if item.get("metadata_status") == "COMPLETE":
            for field in ("license", "maintenance", "security", "compatibility", "requirement_fit", "metadata_status"):
                current[field] = item[field]
    return list(merged.values())[:MAX_CANDIDATES]


def candidate_rejection_reasons(candidate: Mapping[str, Any]) -> list[str]:
    reasons: list[str] = []
    maintenance = candidate.get("maintenance", {})
    if maintenance.get("status") != "PASS":
        reasons.append("maintenance_not_cleared")
    if candidate.get("license", {}).get("policy") in {"BLOCK", "REVIEW", "UNKNOWN"}:
        reasons.append("license_not_automatically_allowed")
    security = candidate.get("security", {})
    if security.get("status") != "PASS":
        reasons.append("security_not_cleared")
    if not _bounded_text(candidate.get("version"), 100):
        reasons.append("exact_version_missing")
    if candidate.get("metadata_status") != "COMPLETE":
        reasons.append("metadata_incomplete")
    compatibility = candidate.get("compatibility", {})
    if any(compatibility.get(field) == "FAIL" for field in ("language", "platform", "runtime", "project_constraints")):
        reasons.append("compatibility_failed")
    if candidate.get("requirement_fit", {}).get("status") == "FAIL":
        reasons.append("requirement_fit_failed")
    if security.get("status") == "PASS" and str(security.get("exact_version_checked", "")) != str(candidate.get("version", "")):
        reasons.append("security_version_identity_mismatch")
    return reasons


def order_candidates(candidates: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    def key(item: Mapping[str, Any]) -> tuple[int, int, int, str]:
        return (
            len(candidate_rejection_reasons(item)),
            0 if item.get("metadata_status") == "COMPLETE" else 1,
            -(int(item.get("popularity", {}).get("stars") or 0)),
            _bounded_text(item.get("candidate_id"), 100),
        )
    return sorted((dict(item) for item in candidates), key=key)[:MAX_CANDIDATES]


def _minimal_trial_env() -> dict[str, str]:
    allowed = {"PATH", "SYSTEMROOT", "WINDIR", "COMSPEC", "TEMP", "TMP", "PATHEXT", "PYTHONUTF8"}
    return {
        key: value for key, value in os.environ.items()
        if key.upper() in allowed and not any(marker in key.upper() for marker in SECRET_ENV_MARKERS)
    } | {"PYTHONUTF8": "1", "PIP_DISABLE_PIP_VERSION_CHECK": "1"}


def run_bounded_python_trial(
    candidate: Mapping[str, Any],
    *,
    timeout: int = TRIAL_TIMEOUT_SECONDS,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> dict[str, Any]:
    result = json.loads(json.dumps(candidate))
    package = _bounded_text(result.get("package_name"), 200)
    version = _bounded_text(result.get("version"), 100)
    if not package or not version:
        result["trial"] = {"status": "BLOCKED", "command": None, "evidence": ["exact package and version required"]}
        return result
    import_name = package.replace("-", "_")
    import_name = {"ffmpeg-python": "ffmpeg", "av": "av", "imageio-ffmpeg": "imageio_ffmpeg", "faiss-cpu": "faiss"}.get(package.lower(), import_name)
    timeout = max(1, min(int(timeout), TRIAL_TIMEOUT_SECONDS))
    workspace = pathlib.Path(tempfile.mkdtemp(prefix="cgkn-executor-trial-"))
    evidence: list[str] = []
    trial_status = "FAIL"
    probe = {
        "ffmpeg-python": "import ffmpeg; value=ffmpeg.input('input.mp4', ss=1).output('frame.png', vframes=1).compile(); assert value",
        "av": "import av; assert callable(av.open)",
        "imageio-ffmpeg": "import imageio_ffmpeg; assert callable(imageio_ffmpeg.get_ffmpeg_version)",
        "pypdf": "import pypdf; assert pypdf.PdfReader",
        "httpx": "import httpx; assert httpx.Client",
        "requests": "import requests; assert requests.Session",
    }.get(package.lower(), f"import {import_name}; assert {import_name}")
    command = f"python -m pip install {package}=={version}; {probe}"
    try:
        venv_dir = workspace / "venv"
        runner([sys.executable, "-m", "venv", str(venv_dir)], cwd=workspace, env=_minimal_trial_env(), capture_output=True, text=True, timeout=timeout, check=True)
        python = venv_dir / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        installed = runner([str(python), "-m", "pip", "install", "--no-input", f"{package}=={version}"], cwd=workspace, env=_minimal_trial_env(), capture_output=True, text=True, timeout=timeout, check=False)
        evidence.append(f"install_exit={installed.returncode}")
        if installed.returncode == 0:
            executed = runner([str(python), "-c", f"{probe}; print('CGKN_TRIAL_OK')"], cwd=workspace, env=_minimal_trial_env(), capture_output=True, text=True, timeout=timeout, check=False)
            evidence.extend([f"runtime_exit={executed.returncode}", _bounded_text(executed.stdout, 200)])
            trial_status = "PASS" if executed.returncode == 0 and "CGKN_TRIAL_OK" in executed.stdout else "FAIL"
    except subprocess.TimeoutExpired:
        trial_status = "BLOCKED"
        evidence.append("trial_timeout")
    except (OSError, subprocess.SubprocessError) as exc:
        trial_status = "BLOCKED"
        evidence.append(_bounded_text(exc, 300))
    finally:
        shutil.rmtree(workspace, ignore_errors=True)
    result["trial"] = {"status": trial_status, "command": command, "evidence": evidence[:8]}
    return result


def _selected_executor(candidate: Mapping[str, Any], intent: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "kind": "CGKNSelectedExecutor",
        "schema_version": SCHEMA_VERSION,
        "capability_id": intent.get("capability_id"),
        "executor": {"type": "external"},
        "package": candidate.get("package_name"),
        "version": candidate.get("version"),
        "repository": candidate.get("repository"),
        "license": candidate.get("license"),
        "maintenance": candidate.get("maintenance"),
        "security": candidate.get("security"),
        "sources": list(candidate.get("sources", [])),
        "metadata_timestamp": _now(),
        "trial_receipt": candidate.get("trial"),
        "trust_provenance": {
            "candidate_id": candidate.get("candidate_id"),
            "package": candidate.get("package_name"),
            "exact_version": candidate.get("version"),
            "repository": candidate.get("repository"),
            "maintenance_evaluated_at": candidate.get("maintenance", {}).get("evaluated_at"),
            "security_evaluated_at": candidate.get("security", {}).get("evaluated_at"),
            "sources": _unique([
                *candidate.get("sources", []),
                *candidate.get("maintenance", {}).get("sources", []),
                *candidate.get("security", {}).get("sources", []),
            ], 16),
        },
        "adapter_required": True,
        "release_authority": False,
    }


def _timestamp_fresh(value: Any, ttl_seconds: int, *, now: datetime | None = None) -> bool:
    timestamp = _parse_timestamp(value)
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    return bool(timestamp and 0 <= (current - timestamp).total_seconds() <= ttl_seconds)


def discovery_result_trust_is_fresh(result: Mapping[str, Any], *, now: datetime | None = None) -> bool:
    selected = result.get("selected_executor")
    if not isinstance(selected, Mapping):
        return False
    maintenance = selected.get("maintenance", {})
    security = selected.get("security", {})
    return (
        _timestamp_fresh(maintenance.get("evaluated_at"), MAINTENANCE_TTL_SECONDS, now=now)
        and _timestamp_fresh(security.get("evaluated_at"), SECURITY_TTL_SECONDS, now=now)
        and security.get("exact_version_checked") == selected.get("version")
        and selected.get("trial_receipt", {}).get("status") == "PASS"
    )


def discover_external_executor(
    capability: Mapping[str, Any],
    *,
    language: str = "python",
    platform: str | None = None,
    constraints: Iterable[str] = (),
    required_interfaces: Iterable[str] = (),
    local_candidates: Iterable[Mapping[str, Any]] = (),
    skill_candidates: Iterable[Mapping[str, Any]] = (),
    allow_network: bool = True,
    opener: Callable[..., Any] | None = None,
    trial_runner: Callable[[Mapping[str, Any]], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    intent = build_search_intent(capability, language=language, platform=platform, constraints=constraints, required_interfaces=required_interfaces)
    if not should_discover_external_executor(capability):
        return {"kind": "CGKNExternalExecutorDiscoveryResult", "status": "NOT_EVALUATED", "route": "agent_build", "intent": intent, "selected_executor": None, "candidates": [], "source_errors": [], "source_status": {"local": "ACTIVE", "skills": "ACTIVE", "facto": "UNAVAILABLE", "github": "NOT_EVALUATED", "pypi": "NOT_EVALUATED", "deps.dev": "NOT_EVALUATED", "osv": "NOT_EVALUATED", "hound": "UNAVAILABLE"}, "pipeline_fallback": "agent_build", "release_authority": False}
    for route, candidates in (("local_reuse", local_candidates), ("skill_reuse", skill_candidates)):
        for candidate in candidates:
            if candidate.get("interface_compatible") and candidate.get("acceptance_compatible", True):
                return {"kind": "CGKNExternalExecutorDiscoveryResult", "status": "PASS", "route": route, "intent": intent, "selected_executor": dict(candidate), "candidates": [], "source_errors": [], "source_status": {"local": "ACTIVE", "skills": "ACTIVE", "facto": "UNAVAILABLE", "github": "NOT_EVALUATED", "pypi": "NOT_EVALUATED", "deps.dev": "NOT_EVALUATED", "osv": "NOT_EVALUATED", "hound": "UNAVAILABLE"}, "pipeline_fallback": None, "release_authority": False}
    if not allow_network:
        return {"kind": "CGKNExternalExecutorDiscoveryResult", "status": "NOT_EVALUATED", "route": "agent_build", "intent": intent, "selected_executor": None, "candidates": [], "source_errors": [SourceError("network", "SOURCE_UNAVAILABLE", "network discovery disabled").as_dict()], "source_status": {"local": "ACTIVE", "skills": "ACTIVE", "facto": "UNAVAILABLE", "github": "UNAVAILABLE", "pypi": "UNAVAILABLE", "deps.dev": "UNAVAILABLE", "osv": "UNAVAILABLE", "hound": "UNAVAILABLE"}, "pipeline_fallback": "agent_build", "release_authority": False}

    github, github_errors = discover_from_github(intent, opener=opener)
    registry, registry_errors = discover_from_registry(intent, opener=opener)
    candidates = order_candidates(merge_candidates([*registry, *github]))
    errors = [*github_errors, *registry_errors]
    trust_evaluated: list[dict[str, Any]] = []
    for index, candidate in enumerate(candidates):
        if index >= MAX_TRUST_CANDIDATES:
            candidate["rejection_reasons"] = ["trust_candidate_limit_reached"]
            trust_evaluated.append(candidate)
            continue
        candidate, maintenance_errors = enrich_github_maintenance(candidate, opener=opener)
        errors.extend(maintenance_errors)
        candidate, security_error = enrich_security_from_osv(candidate, opener=opener)
        if security_error:
            errors.append(security_error)
        trust_evaluated.append(candidate)
    candidates = order_candidates(trust_evaluated)
    runner = trial_runner or run_bounded_python_trial
    evaluated: list[dict[str, Any]] = []
    trial_count = 0
    selected: dict[str, Any] | None = None
    for candidate in candidates:
        rejection = candidate_rejection_reasons(candidate)
        if rejection or trial_count >= MAX_TRIAL_CANDIDATES or selected is not None:
            candidate["rejection_reasons"] = rejection or [
                "higher_priority_candidate_selected" if selected is not None else "trial_candidate_limit_reached"
            ]
            evaluated.append(candidate)
            continue
        trial_count += 1
        candidate = runner(candidate)
        if candidate.get("trial", {}).get("status") == "PASS" and not candidate_rejection_reasons(candidate):
            selected = _selected_executor(candidate, intent)
            evaluated.append(candidate)
            continue
        candidate["rejection_reasons"] = ["trial_not_passed"]
        evaluated.append(candidate)
    return {
        "kind": "CGKNExternalExecutorDiscoveryResult",
        "schema_version": SCHEMA_VERSION,
        "status": "PASS" if selected else "NOT_EVALUATED",
        "route": "external" if selected else "agent_build",
        "intent": intent,
        "selected_executor": selected,
        "candidates": evaluated[:MAX_CANDIDATES],
        "source_errors": errors[:20],
        "source_status": {
            "local": "ACTIVE",
            "skills": "ACTIVE",
            "facto": "UNAVAILABLE",
            "github": "ACTIVE" if not github_errors else ("ACTIVE" if github else "UNAVAILABLE"),
            "pypi": "ACTIVE" if any("pypi" in item.get("sources", []) for item in candidates) else "UNAVAILABLE",
            "deps.dev": "ACTIVE" if any("deps.dev" in item.get("sources", []) for item in candidates) else "UNAVAILABLE",
            "osv": "ACTIVE" if any("osv" in item.get("security", {}).get("sources", []) for item in candidates) else "UNAVAILABLE",
            "hound": "UNAVAILABLE",
        },
        "trial_candidate_count": trial_count,
        "pipeline_fallback": None if selected else "agent_build",
        "release_authority": False,
    }

