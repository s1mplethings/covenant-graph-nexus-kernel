"""Signed release-authorization verification for non-Worker delivery sources.

Trust model
-----------
The run store and the candidate workspace are writable by the executing agent.
Nothing inside them can prove *who* authorized a release.  This module only
accepts a release authorization that is signed with Ed25519 by a key listed in
a trust anchor file that lives outside both writable roots.  The verifier never
reads a private key.

The trust anchor file still has to be protected by the host (filesystem ACL,
separate OS account, HSM, or a remote signing service).  If the agent can write
the anchor or invoke the signer, this module provides tamper *evidence* only,
not a real trust boundary; callers must report PENDING_TRUST_ANCHOR in that
case.  See docs/RELEASE_AUTHORIZATION.md for the deployment contract.
"""
from __future__ import annotations

import base64
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

AUTHORIZATION_KIND = "SignedReleaseAuthorization"
ANCHOR_KIND = "ReleaseTrustAnchor"
SCHEMA_VERSION = "1"
def _b64(value, validate=False):
    return base64.b64decode(value, validate=validate)


class ReleaseAuthorizationError(ValueError):
    """Fail-closed authorization error; never downgraded to a warning."""


def _canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"), allow_nan=False)


def payload_bytes(document):
    """Canonical bytes covered by the signature (everything except signature)."""
    if not isinstance(document, dict):
        raise ReleaseAuthorizationError("authorization must be an object")
    signed = {key: value for key, value in document.items() if key != "signature"}
    return _canonical(signed).encode("utf-8")


def manifest_digest(manifest):
    normalized = normalize_manifest(manifest)
    return hashlib.sha256(_canonical(normalized).encode("utf-8")).hexdigest()


def normalize_manifest(manifest):
    if not isinstance(manifest, dict) or not manifest:
        raise ReleaseAuthorizationError("delivery manifest must be a non-empty object")
    normalized = {}
    for name, value in sorted(manifest.items()):
        if not isinstance(name, str) or not name:
            raise ReleaseAuthorizationError("manifest artifact name is invalid")
        digest = str(value).removeprefix("sha256:").lower()
        if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
            raise ReleaseAuthorizationError("manifest artifact hash is not SHA-256: " + name)
        normalized[name] = digest
    return normalized


def _parse_time(value, field):
    if not isinstance(value, str) or not value.strip():
        raise ReleaseAuthorizationError("authorization " + field + " is missing")
    text = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise ReleaseAuthorizationError("authorization " + field + " is not ISO-8601") from exc
    if parsed.tzinfo is None:
        raise ReleaseAuthorizationError("authorization " + field + " needs a timezone")
    return parsed.astimezone(timezone.utc)


def _outside(path, root, label):
    try:
        if path.is_relative_to(root):
            raise ReleaseAuthorizationError(label + " is inside an untrusted writable root")
    except OSError as exc:
        raise ReleaseAuthorizationError(label + " cannot be resolved") from exc


def load_trust_anchor(anchor_path, *, store_root, workspace_root):
    """Load the protected public-key configuration; never a private key."""
    try:
        anchor = Path(anchor_path).resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise ReleaseAuthorizationError("release trust anchor is missing") from exc
    if anchor.is_symlink():
        raise ReleaseAuthorizationError("release trust anchor must not be a symlink")
    _outside(anchor, Path(store_root).resolve(), "release trust anchor")
    _outside(anchor, Path(workspace_root).resolve(), "release trust anchor")
    try:
        document = json.loads(anchor.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeError) as exc:
        raise ReleaseAuthorizationError("release trust anchor is unreadable") from exc
    if (not isinstance(document, dict) or document.get("kind") != ANCHOR_KIND
            or str(document.get("schema_version")) != SCHEMA_VERSION
            or not document.get("authority_id") or not isinstance(document.get("keys"), dict)):
        raise ReleaseAuthorizationError("release trust anchor contract is invalid")
    for key_id, key in document["keys"].items():
        if (not isinstance(key, dict) or not key_id
                or key.get("algorithm") != "ed25519"
                or not key.get("public_key_b64")):
            raise ReleaseAuthorizationError("release trust anchor key is invalid: " + str(key_id))
        try:
            raw = _b64(str(key["public_key_b64"]), validate=True)
        except Exception as exc:
            raise ReleaseAuthorizationError("release trust anchor key is not base64") from exc
        if len(raw) != 32:
            raise ReleaseAuthorizationError("release trust anchor key is not Ed25519")
    document["_path"] = str(anchor)
    return document


def _verify_signature(document, anchor, key_id):
    keys = anchor["keys"]
    if key_id not in keys:
        raise ReleaseAuthorizationError("authorization signer is not in the trust anchor")
    signature = document.get("signature")
    if (not isinstance(signature, dict) or signature.get("algorithm") != "ed25519"
            or signature.get("key_id") != key_id or not signature.get("value_b64")):
        raise ReleaseAuthorizationError("authorization signature block is invalid")
    try:
        blob = _b64(str(signature["value_b64"]), validate=True)
    except Exception as exc:
        raise ReleaseAuthorizationError("authorization signature is not base64") from exc
    if len(blob) != 64:
        raise ReleaseAuthorizationError("authorization signature is not Ed25519")
    try:
        from cryptography.exceptions import InvalidSignature
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    except ImportError as exc:  # fail closed, never fall back to unsigned JSON
        raise ReleaseAuthorizationError("Ed25519 verifier is unavailable") from exc
    public = Ed25519PublicKey.from_public_bytes(
        _b64(str(anchor["keys"][key_id]["public_key_b64"]), validate=True))
    try:
        public.verify(blob, payload_bytes(document))
    except InvalidSignature as exc:
        raise ReleaseAuthorizationError("authorization signature does not match") from exc


def verify_release_authorization(
    document,
    *,
    anchor_path,
    store_root,
    workspace_root,
    expected_logical_task_id,
    manifest,
    now=None,
):
    """Verify one signed, batch-scoped release authorization.

    Binds release identity, logical task, exact delivery manifest, per-artifact
    SHA-256 and author type, per-file authorization/review/B10/B11 hashes, and
    an expiry window.  A signature from a key outside the trust anchor, or a
    document whose bytes changed after signing, fails closed.
    """
    if not isinstance(document, dict) or document.get("kind") != AUTHORIZATION_KIND:
        raise ReleaseAuthorizationError("signed release authorization is missing or mistyped")
    if str(document.get("schema_version")) != SCHEMA_VERSION:
        raise ReleaseAuthorizationError("signed release authorization schema is unsupported")
    anchor = load_trust_anchor(anchor_path, store_root=store_root, workspace_root=workspace_root)
    signer = document.get("signer")
    if not isinstance(signer, dict) or not signer.get("key_id"):
        raise ReleaseAuthorizationError("authorization signer identity is missing")
    key_id = signer["key_id"]
    _verify_signature(document, anchor, key_id)
    if document.get("authority_id") != anchor["authority_id"]:
        raise ReleaseAuthorizationError("authorization authority differs from the trust anchor")

    moment = now or datetime.now(timezone.utc)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    not_before = _parse_time(document.get("not_before"), "not_before")
    expires_at = _parse_time(document.get("expires_at"), "expires_at")
    if not_before > expires_at:
        raise ReleaseAuthorizationError("authorization time window is inverted")
    if moment.astimezone(timezone.utc) < not_before:
        raise ReleaseAuthorizationError("authorization is not valid yet")
    if moment.astimezone(timezone.utc) > expires_at:
        raise ReleaseAuthorizationError("authorization has expired")

    if not document.get("release_id"):
        raise ReleaseAuthorizationError("authorization release_id is missing")
    if document.get("logical_task_id") != expected_logical_task_id:
        raise ReleaseAuthorizationError("authorization belongs to another logical task")
    nonce = str(document.get("nonce", ""))
    if len(nonce) < 32 or any(ch not in "0123456789abcdef" for ch in nonce.lower()):
        raise ReleaseAuthorizationError("authorization nonce is missing or too weak")
    if not document.get("scope"):
        raise ReleaseAuthorizationError("authorization scope is missing")

    normalized = normalize_manifest(manifest)
    if document.get("candidate_source_manifest_sha256") != manifest_digest(normalized):
        raise ReleaseAuthorizationError("authorization does not bind the delivered manifest")

    artifacts = document.get("artifacts")
    if not isinstance(artifacts, dict) or set(artifacts) != set(normalized):
        raise ReleaseAuthorizationError("authorization artifact coverage differs from the manifest")
    for name, digest in normalized.items():
        entry = artifacts.get(name)
        if not isinstance(entry, dict) or entry.get("sha256") != digest:
            raise ReleaseAuthorizationError("authorization artifact hash mismatch: " + name)
        author_type = entry.get("author_type")
        if author_type not in {"worker", "agent"}:
            raise ReleaseAuthorizationError("authorization author_type is invalid: " + name)
        if author_type == "agent":
            for field in ("author_identity", "authorization_sha256", "review_sha256",
                          "b10_certificate_sha256", "b11_acceptance_sha256"):
                if not entry.get(field):
                    raise ReleaseAuthorizationError(
                        "agent authorization is incomplete for " + name + ": " + field)
            if "b10_section_sha256" not in entry:
                raise ReleaseAuthorizationError(
                    "agent authorization omits B10 coverage claim for " + name)
    return {
        **{key: value for key, value in document.items() if key != "signature"},
        "trust_anchor_path": anchor["_path"],
        "signer_key": {key: value for key, value in anchor["keys"][key_id].items()
                       if key != "public_key_b64"},
        "manifest_digest": manifest_digest(normalized),
    }
