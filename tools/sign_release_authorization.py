#!/usr/bin/env python3
"""Sign one batch-scoped release authorization with a protected Ed25519 key.

Run this OUTSIDE the agent workspace, from a controller/account that can read
the private key.  The verifier never calls this module and never needs the
private key.  Do not check a production private key into the repository and do
not store it in the run store or candidate workspace.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import pathlib
import sys


def _sha(path):
    return hashlib.sha256(pathlib.Path(path).read_bytes()).hexdigest()


def _read(path):
    return json.loads(pathlib.Path(path).read_text(encoding="utf-8"))


def _resolve(store_root, ref):
    root = pathlib.Path(store_root).resolve()
    path = (root / ref["path"]).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise SystemExit("referenced object is outside the run store: " + str(path))
    if _sha(path) != ref["sha256"]:
        raise SystemExit("referenced object hash changed: " + str(path))
    return path


def build_artifacts(*, store_root, manifest, source_imports):
    artifacts = {}
    for path in sorted(pathlib.Path(source_imports).glob("*.json")):
        doc = _read(path)
        name = doc.get("artifact")
        if name not in manifest:
            continue
        if doc.get("sha256") != manifest[name]:
            raise SystemExit("source import does not match the delivery manifest: " + str(name))
        if doc.get("kind") == "AuthorizedAgentSource":
            auth = _resolve(store_root, doc["authorization_ref"])
            review_path = _resolve(store_root, doc["review_ref"])
            review = _read(review_path)
            b10_path = _resolve(store_root, review["b10_certificate_ref"])
            b11_path = _resolve(store_root, review["b11_acceptance_ref"])
            b10 = _read(b10_path)
            sections = b10.get("relevant_section_hashes", {})
            artifacts[name] = {
                "sha256": manifest[name],
                "author_type": "agent",
                "author_identity": doc.get("author_identity", ""),
                "authorization_sha256": _sha(auth),
                "review_sha256": _sha(review_path),
                "b10_certificate_sha256": _sha(b10_path),
                "b11_acceptance_sha256": _sha(b11_path),
                "b10_section_sha256": sections.get(name + "#full"),
            }
        elif doc.get("kind") == "ImportedWorkerSource":
            artifacts[name] = {
                "sha256": manifest[name],
                "author_type": "worker",
                "receipt_sha256": doc.get("receipt_ref", {}).get("sha256"),
                "source_project_id": doc.get("source_project_id"),
                "source_run_id": doc.get("source_run_id"),
            }
        else:
            raise SystemExit("unknown source import kind: " + str(doc.get("kind")))
    missing = sorted(set(manifest) - set(artifacts))
    if missing:
        raise SystemExit("manifest artifacts without source imports: " + ",".join(missing))
    return artifacts


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-store", required=True,
                        help="FileRunStore root (the store, not the run directory)")
    parser.add_argument("--run-relative", required=True,
                        help="project_id/run_id relative to the run store")
    parser.add_argument("--manifest", required=True,
                        help="JSON file mapping artifact name to SHA-256")
    parser.add_argument("--release-id", required=True)
    parser.add_argument("--logical-task-id", required=True)
    parser.add_argument("--private-key", required=True,
                        help="PKCS8 PEM Ed25519 private key outside agent-writable roots")
    parser.add_argument("--key-id", required=True)
    parser.add_argument("--authority-id", default="veriarbor-release-authority")
    parser.add_argument("--anchor-out", required=True,
                        help="protected public-key anchor output path")
    parser.add_argument("--out", required=True,
                        help="signed release authorization output path")
    parser.add_argument("--not-before", required=True)
    parser.add_argument("--expires-at", required=True)
    parser.add_argument("--nonce", required=True)
    parser.add_argument("--scope", default="final_delivery_source_provenance")
    parser.add_argument("--principal", default="user")
    args = parser.parse_args(argv)

    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
    from cgkn.state.release_authorization import manifest_digest, normalize_manifest, payload_bytes

    try:
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    except ImportError:
        raise SystemExit("cryptography is required to sign")

    store = pathlib.Path(args.run_store).resolve()
    run = store / args.run_relative
    manifest = normalize_manifest(_read(args.manifest))
    artifacts = build_artifacts(store_root=store, manifest=manifest,
                                source_imports=run / "source_imports")
    for name, entry in artifacts.items():
        if entry["author_type"] == "agent" and entry["b10_section_sha256"] is not None:
            if entry["b10_section_sha256"] != manifest[name]:
                raise SystemExit("B10 section hash does not match delivered bytes: " + name)

    document = {
        "kind": "SignedReleaseAuthorization",
        "schema_version": "1",
        "authority_id": args.authority_id,
        "release_id": args.release_id,
        "logical_task_id": args.logical_task_id,
        "scope": args.scope,
        "not_before": args.not_before,
        "expires_at": args.expires_at,
        "nonce": args.nonce,
        "candidate_source_manifest_sha256": manifest_digest(manifest),
        "artifacts": artifacts,
        "signer": {"key_id": args.key_id, "principal": args.principal},
    }
    key = serialization.load_pem_private_key(
        pathlib.Path(args.private_key).read_bytes(), password=None)
    if not isinstance(key, Ed25519PrivateKey):
        raise SystemExit("private key is not Ed25519")
    signature = key.sign(payload_bytes(document))
    document["signature"] = {
        "algorithm": "ed25519",
        "key_id": args.key_id,
        "value_b64": base64.b64encode(signature).decode("ascii"),
    }
    public = key.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    anchor = {
        "kind": "ReleaseTrustAnchor",
        "schema_version": "1",
        "authority_id": args.authority_id,
        "keys": {
            args.key_id: {
                "algorithm": "ed25519",
                "public_key_b64": base64.b64encode(public).decode("ascii"),
                "principal": args.principal,
                "purpose": "final_delivery_source_authorization",
            }
        },
    }
    anchor_path = pathlib.Path(args.anchor_out).resolve()
    anchor_path.parent.mkdir(parents=True, exist_ok=True)
    anchor_path.write_text(json.dumps(anchor, ensure_ascii=False, indent=2) + "\n",
                           encoding="utf-8")
    out = pathlib.Path(args.out).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n",
                   encoding="utf-8")
    print(json.dumps({"status": "SIGNED", "authorization": str(out),
                      "anchor": str(anchor_path),
                      "manifest_digest": document["candidate_source_manifest_sha256"],
                      "release_id": args.release_id}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
