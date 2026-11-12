"""Isolated P01-P19 security tests for the P11 self-authorization fix.

All test stores and workspaces are copied under a temporary directory.  The
formal run store, candidate, ZIP and delivery evidence are read-only inputs.
The Ed25519 private key used here is a disposable test fixture and must never
sign a formal release.
"""
from __future__ import annotations

import base64
import hashlib
import json
import shutil
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

H = Path(r"F:\CGKN-LeanLoop-V1-20261101")
R = Path(r"F:\CGKN-ITER-132\production-core-convergence-v1\promotion\run-05")
M = Path(r"F:\CGKN-LeanLoop-V1-20261101\migration\veriarbor")
APP = R / "DOGFOOD_M12_20261106" / "application"
FORMAL = R / "FINAL_VALIDATION_20261106_RUN3/state/iter132-promotion-studio/final-validation-01"
DELIVERY = R / "PROMOTION_DELIVERY_M12_FINAL_20261106"
PID = "iter132-promotion-studio"
RID = "final-validation-01"

from cgkn.state import FileRunStore
from cgkn.state.acceptance import GoalAcceptance, identity
from cgkn.state.provenance import ProvenanceGate, ProvenanceError
from cgkn.state.release_authorization import (
    ReleaseAuthorizationError,
    manifest_digest,
    normalize_manifest,
    payload_bytes,
)
from scripts import canonical_evidence_hash, canonical_delivery_manifest
from scripts import production_candidate_provenance
from tools.sign_release_authorization import build_artifacts

try:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
except ImportError as exc:  # pragma: no cover
    raise SystemExit("cryptography with Ed25519 is required") from exc

PROTECTED = Path(r"C:\Users\sunom\AppData\Local\Temp\opencode\p11fix_protected")
PROTECTED.mkdir(parents=True, exist_ok=True)
PRIVATE_KEY_PATH = PROTECTED / "release-private.pem"
ANCHOR_PATH = PROTECTED / "release-trust-anchor.json"
KEY_ID = "fixture-release-2026-11"
AUTHORITY_ID = "veriarbor-release-authority"
NOW = datetime.now(timezone.utc)
NOT_BEFORE = (NOW - timedelta(hours=1)).isoformat()
EXPIRES_AT = (NOW + timedelta(days=30)).isoformat()


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write(path, doc):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n",
                          encoding="utf-8")


def ensure_fixture():
    if not PRIVATE_KEY_PATH.exists():
        key = Ed25519PrivateKey.generate()
        PRIVATE_KEY_PATH.write_bytes(key.private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption()))
    key = serialization.load_pem_private_key(PRIVATE_KEY_PATH.read_bytes(), password=None)
    if not ANCHOR_PATH.exists():
        public = key.public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw)
        write(ANCHOR_PATH, {
            "kind": "ReleaseTrustAnchor", "schema_version": "1",
            "authority_id": AUTHORITY_ID,
            "keys": {KEY_ID: {
                "algorithm": "ed25519",
                "public_key_b64": base64.b64encode(public).decode("ascii"),
                "principal": "fixture-user",
                "purpose": "final_delivery_source_authorization",
            }},
        })
    return key


TEST_KEY = ensure_fixture()


def make_case(name):
    root = Path(tempfile.mkdtemp(prefix=f"p11fix-{name}-"))
    state = root / "state"
    workspace = root / "workspace"
    shutil.copytree(FORMAL, state / PID / RID,
                    ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache"))
    shutil.copytree(APP, workspace,
                    ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache"))
    store = FileRunStore(state)
    run = store.run_dir(PID, RID)
    profile = read(run / "project_profile.json")
    if profile.get("workspace") != str(workspace):
        profile["workspace"] = str(workspace)
        write(run / "project_profile.json", profile)
    goal = read(run / "goal_acceptance.json")
    acceptance = GoalAcceptance(store, PID, RID, profile["requirements"],
                                goal["checker_bindings"])
    manifest = canonical_evidence_hash.candidate_source_manifest(workspace)
    (run / "release_authorization.json").unlink(missing_ok=True)
    case = SimpleNamespace(root=root, state=state, workspace=workspace, store=store,
                           run=run, acceptance=acceptance, manifest=manifest,
                           gate=None)
    bind_gate(case)
    return case


def bind_gate(case, *, anchor=ANCHOR_PATH, authorization=None):
    case.gate = ProvenanceGate(
        case.store, PID, RID,
        release_trust_anchor=anchor,
        release_authorization=authorization or (case.run / "release_authorization.json"))


def sign_payload(payload, *, key=TEST_KEY, key_id=KEY_ID):
    signature = key.sign(payload_bytes(payload))
    return {**payload, "signature": {
        "algorithm": "ed25519", "key_id": key_id,
        "value_b64": base64.b64encode(signature).decode("ascii")}}


def build_payload(case, *, release_id="rel-m12-001", logical_task_id=None,
                  manifest=None, mutate=None):
    manifest = normalize_manifest(manifest or case.manifest)
    artifacts = build_artifacts(store_root=case.store.root, manifest=manifest,
                                source_imports=case.run / "source_imports")
    payload = {
        "kind": "SignedReleaseAuthorization",
        "schema_version": "1",
        "authority_id": AUTHORITY_ID,
        "release_id": release_id,
        "logical_task_id": logical_task_id or f"{PID}/{RID}",
        "scope": "final_delivery_source_manifest",
        "not_before": NOT_BEFORE,
        "expires_at": EXPIRES_AT,
        "nonce": hashlib.sha256((release_id + (logical_task_id or "")).encode()).hexdigest(),
        "candidate_source_manifest_sha256": manifest_digest(manifest),
        "artifacts": artifacts,
        "signer": {"key_id": KEY_ID, "principal": "fixture-user"},
    }
    if mutate:
        mutate(payload)
    return payload


def sign_case(case, *, out=None, key=TEST_KEY, **kwargs):
    payload = build_payload(case, **kwargs)
    doc = sign_payload(payload, key=key)
    write(out or (case.run / "release_authorization.json"), doc)
    return doc


def attempt(fn):
    try:
        result = fn()
        return "ACCEPT", None, result
    except Exception as exc:  # noqa: BLE001 - test harness records exact errors
        return "REJECT", f"{type(exc).__name__}: {str(exc)[:700]}", None


def rewrite_review_refs(case, review_path):
    review_sha = sha(review_path)
    changed = 0
    for path in (case.run / "source_imports").glob("*.json"):
        doc = read(path)
        if doc.get("kind") == "AuthorizedAgentSource":
            doc["review_ref"] = {
                "path": review_path.resolve().relative_to(case.store.root).as_posix(),
                "sha256": review_sha,
            }
            new_path = case.run / "source_imports" / (identity(doc) + ".json")
            write(new_path, doc)
            if new_path != path:
                path.unlink()
            changed += 1
    return changed


def rewrite_agent_import_sha(case, artifact, digest):
    for path in (case.run / "source_imports").glob("*.json"):
        doc = read(path)
        if doc.get("kind") == "AuthorizedAgentSource" and doc.get("artifact") == artifact:
            doc["sha256"] = digest
            new_path = case.run / "source_imports" / (identity(doc) + ".json")
            write(new_path, doc)
            if new_path != path:
                path.unlink()
            return


def find_doc(case, kind, artifact=None):
    for path in sorted((case.run / "source_imports").glob("*.json")):
        doc = read(path)
        if doc.get("kind") == kind and (artifact is None or doc.get("artifact") == artifact):
            return path, doc
    raise RuntimeError(f"doc not found {kind} {artifact}")


# --------------------------------------------------------------------------
# P01-P10: preserve the original reverse-test contract.
# --------------------------------------------------------------------------

def p01(case):
    _, doc = find_doc(case, "AuthorizedAgentSource", "README.md")
    (case.run / doc["authorization_ref"]["path"].split("/", 2)[-1]).unlink()
    case.gate.delivery_sources(case.acceptance, case.workspace, case.manifest)


def p02(case):
    with (case.workspace / "README.md").open("a", encoding="utf-8") as handle:
        handle.write("\nunauthorized\n")
    case.gate.delivery_sources(case.acceptance, case.workspace, case.manifest)


def p03(case):
    path, doc = find_doc(case, "AuthorizedAgentSource", "README.md")
    doc["author_type"] = "worker"
    new_path = case.run / "source_imports" / (identity(doc) + ".json")
    write(new_path, doc)
    path.unlink()
    case.gate.delivery_sources(case.acceptance, case.workspace, case.manifest)


def p04(case):
    review_path = case.run / "agent_reviews" / "B11_ACCEPTANCE.json"
    review = read(review_path)
    review["observed"]["observed"]["value"] = False
    write(review_path, review)
    case.gate.delivery_sources(case.acceptance, case.workspace, case.manifest)


def p05(case):
    path, doc = find_doc(case, "ImportedWorkerSource", "early_main.py")
    doc["receipt_ref"]["sha256"] = "0" * 64
    new_path = case.run / "source_imports" / (identity(doc) + ".json")
    write(new_path, doc)
    path.unlink()
    case.gate.delivery_sources(case.acceptance, case.workspace, case.manifest)


def p06(case):
    with (case.workspace / "early_main.py").open("a", encoding="utf-8") as handle:
        handle.write("\n# tampered\n")
    case.gate.delivery_sources(case.acceptance, case.workspace, case.manifest)


def p07(case):
    path, doc = find_doc(case, "AuthorizedAgentSource", "README.md")
    doc["sha256"] = "ed2393761e5b4a6cd623e04ec108abaeb212e6058c90c279a792aad870d781d7"
    new_path = case.run / "source_imports" / (identity(doc) + ".json")
    write(new_path, doc)
    path.unlink()
    case.gate.delivery_sources(case.acceptance, case.workspace, case.manifest)


def p08(case):
    (case.run / "agent_reviews" / "B10_CERTIFICATE.json").unlink()
    case.gate.delivery_sources(case.acceptance, case.workspace, case.manifest)


def p09(case):
    unrelated = M / "M12_ACCEPTANCE.json"
    inspection = production_candidate_provenance.inspect(
        unrelated, expected_candidate_dir=case.workspace,
        release_trust_anchor=ANCHOR_PATH,
        release_authorization=case.run / "release_authorization.json")
    if inspection.get("status") == "PASS":
        raise AssertionError("unrelated provenance reference accepted")
    return {"control_result": "REJECT", "failures": inspection.get("failures")}


def p10(case):
    result = case.gate.delivery_sources(case.acceptance, case.workspace, case.manifest)
    if result.get("status") != "TRUSTED":
        raise AssertionError("baseline rejected")


# --------------------------------------------------------------------------
# P11-P19: new self-authorization and trust-root scenarios.
# --------------------------------------------------------------------------

def p11(case):
    """Change README, rewrite auth/review/source import, recompute manifest."""
    with (case.workspace / "README.md").open("a", encoding="utf-8") as handle:
        handle.write("\nSELF-AUTHORIZED CHANGE\n")
    new_hash = sha(case.workspace / "README.md")
    manifest = canonical_evidence_hash.candidate_source_manifest(case.workspace)
    auth_paths = sorted((case.run / "agent_authorizations").glob("*.json"))
    review_paths = sorted((case.run / "agent_reviews").glob("*.json"))
    auth = read(auth_paths[0])
    review = read(review_paths[0])
    auth["artifacts"]["README.md"] = new_hash
    review["artifacts"]["README.md"] = new_hash
    write(case.run / "agent_authorizations" / (identity(auth) + ".json"), auth)
    write(case.run / "agent_reviews" / (identity(review) + ".json"), review)
    rewrite_agent_import_sha(case, "README.md", new_hash)
    case.gate.delivery_sources(case.acceptance, case.workspace, manifest)


def p12(case):
    """Rewrite the signed authorization bytes without the private key."""
    with (case.workspace / "README.md").open("a", encoding="utf-8") as handle:
        handle.write("\nSELF-AUTHORIZED CHANGE\n")
    new_hash = sha(case.workspace / "README.md")
    manifest = canonical_evidence_hash.candidate_source_manifest(case.workspace)
    rewrite_agent_import_sha(case, "README.md", new_hash)
    doc = read(case.run / "release_authorization.json")
    doc["candidate_source_manifest_sha256"] = manifest_digest(manifest)
    doc["artifacts"]["README.md"]["sha256"] = new_hash
    write(case.run / "release_authorization.json", doc)
    case.gate.delivery_sources(case.acceptance, case.workspace, manifest)


def p13(case):
    """Replace the trust anchor / policy with an attacker-controlled copy."""
    attacker = Ed25519PrivateKey.generate()
    attacker_public = attacker.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    attacker_anchor = {
        "kind": "ReleaseTrustAnchor", "schema_version": "1",
        "authority_id": AUTHORITY_ID,
        "keys": {"attacker": {
            "algorithm": "ed25519",
            "public_key_b64": base64.b64encode(attacker_public).decode("ascii"),
            "principal": "attacker"}},
    }
    store_anchor = case.run / "attacker_anchor.json"
    write(store_anchor, attacker_anchor)
    payload = build_payload(case)
    payload["signer"] = {"key_id": "attacker", "principal": "attacker"}
    forged = sign_payload(payload, key=attacker, key_id="attacker")
    write(case.run / "release_authorization.json", forged)
    # A. Gate told to use the store anchor must refuse the anchor itself.
    bind_gate(case, anchor=store_anchor)
    attempt_a = attempt(lambda: case.gate.delivery_sources(
        case.acceptance, case.workspace, case.manifest))
    # B. Gate using the protected anchor must refuse the attacker signature.
    bind_gate(case, anchor=ANCHOR_PATH)
    attempt_b = attempt(lambda: case.gate.delivery_sources(
        case.acceptance, case.workspace, case.manifest))
    # C. A malicious verifier dropped in the workspace must not be imported.
    fake = case.workspace / "cgkn" / "state"
    fake.mkdir(parents=True, exist_ok=True)
    (fake / "release_authorization.py").write_text(
        "def verify_release_authorization(*a, **k):\n    return {'ok': True}\n",
        encoding="utf-8")
    (fake / "provenance.py").write_text(
        "class ProvenanceGate:\n    def delivery_sources(self, *a, **k):\n"
        "        return {'status': 'TRUSTED'}\n", encoding="utf-8")
    import cgkn.state.provenance as loaded
    import cgkn.state.release_authorization as loaded_ra
    for loaded_path in (Path(loaded.__file__).resolve(), Path(loaded_ra.__file__).resolve()):
        if loaded_path.is_relative_to(case.workspace):
            raise AssertionError("verifier was imported from the agent workspace")
    if attempt_b[0] != "REJECT":
        raise AssertionError("attacker anchor/signature was accepted")
    if attempt_a[0] != "REJECT":
        raise AssertionError("store-local anchor was accepted")
    return {"control_result": "REJECT"}


def p14(case):
    """Modify reviewed content while main.py is unchanged."""
    # A. Rewrite B10's README section and re-sign an internally inconsistent
    #    batch.  The signer is valid, but the certified section no longer
    #    matches the delivered bytes, so the verifier must reject.
    review_path = case.run / "agent_reviews" / "3b04ddaf0f660faddf674d9047fcc49e0c3ef9a9d74df75aa4c57b141f5fcb59.json"
    review = read(review_path)
    b10_path = case.run / "agent_reviews" / "B10_CERTIFICATE.json"
    b10 = read(b10_path)
    b10["relevant_section_hashes"]["README.md#full"] = "0" * 64
    write(b10_path, b10)
    review["b10_certificate_ref"]["sha256"] = sha(b10_path)
    write(review_path, review)
    rewrite_review_refs(case, review_path)
    sign_case(case, manifest=case.manifest)
    attempt_a = attempt(lambda: case.gate.delivery_sources(
        case.acceptance, case.workspace, case.manifest))
    # B. Change README bytes and register the new hash, keep the old signature.
    with (case.workspace / "README.md").open("a", encoding="utf-8") as handle:
        handle.write("\nREVIEWED CONTENT CHANGED\n")
    new_hash = sha(case.workspace / "README.md")
    rewrite_agent_import_sha(case, "README.md", new_hash)
    manifest = canonical_evidence_hash.candidate_source_manifest(case.workspace)
    attempt_b = attempt(lambda: case.gate.delivery_sources(
        case.acceptance, case.workspace, manifest))
    if attempt_a[0] != "REJECT" or attempt_b[0] != "REJECT":
        raise AssertionError(f"reviewed-content change accepted: {attempt_a} {attempt_b}")
    # C. The same reviewed-content rule must hold for TEST_PLAN and the test
    #    file, independently of main.py.
    for artifact in ("TEST_PLAN.md", "tests/test_promotion_gui.py"):
        sub = make_case("p14-" + artifact.replace("/", "-").replace(".", "-"))
        sign_case(sub, manifest=sub.manifest)
        with (sub.workspace / artifact).open("a", encoding="utf-8") as handle:
            handle.write("\nREVIEWED CONTENT CHANGED\n")
        rewrite_agent_import_sha(sub, artifact, sha(sub.workspace / artifact))
        sub_manifest = canonical_evidence_hash.candidate_source_manifest(sub.workspace)
        sub_status, sub_error, _ = attempt(lambda: sub.gate.delivery_sources(
            sub.acceptance, sub.workspace, sub_manifest))
        if sub_status != "REJECT":
            raise AssertionError(f"reviewed content accepted for {artifact}: {sub_error}")
    return {"control_result": "REJECT"}


def p15(case):
    """Rewrite B11 and recompute ordinary hashes without a new signature."""
    b11_path = case.run / "agent_reviews" / "B11_ACCEPTANCE.json"
    b11 = read(b11_path)
    b11["checks"] = list(b11.get("checks", [])) + ["AGENT-AUTHORED EXTRA CHECK"]
    write(b11_path, b11)
    review_path = case.run / "agent_reviews" / "3b04ddaf0f660faddf674d9047fcc49e0c3ef9a9d74df75aa4c57b141f5fcb59.json"
    review = read(review_path)
    review["b11_acceptance_ref"]["sha256"] = sha(b11_path)
    write(review_path, review)
    rewrite_review_refs(case, review_path)
    case.gate.delivery_sources(case.acceptance, case.workspace, case.manifest)


def p16(case):
    """Use another candidate's valid authorization."""
    other = make_case("p16-other")
    with (other.workspace / "pyproject.toml").open("a", encoding="utf-8") as handle:
        handle.write("\n# other candidate\n")
    other_manifest = canonical_evidence_hash.candidate_source_manifest(other.workspace)
    rewrite_agent_import_sha(other, "pyproject.toml",
                             sha(other.workspace / "pyproject.toml"))
    other_release = other.run / "release_authorization.json"
    sign_case(other, manifest=other_manifest, release_id="rel-other-candidate")
    # A. Replay other candidate's document into this case.
    shutil.copy2(other_release, case.run / "release_authorization.json")
    attempt_a = attempt(lambda: case.gate.delivery_sources(
        case.acceptance, case.workspace, case.manifest))
    # B. A valid signature for a different logical task must also fail.
    sign_case(case, logical_task_id="another-logical-task")
    attempt_b = attempt(lambda: case.gate.delivery_sources(
        case.acceptance, case.workspace, case.manifest))
    if attempt_a[0] != "REJECT" or attempt_b[0] != "REJECT":
        raise AssertionError(f"cross-candidate release accepted: {attempt_a} {attempt_b}")
    return {"control_result": "REJECT"}


def p17(case):
    """Change ZIP bytes while the old manifest/authorization stay unchanged."""
    import zipfile
    manifest_doc = read(DELIVERY / "delivery_manifest.json")
    source_zip = DELIVERY / "final_project_bundle.zip"
    baseline = canonical_delivery_manifest.inspect_zip_entries(source_zip)
    if baseline.get("status") != "PASS":
        raise AssertionError("baseline ZIP inspection did not PASS")
    if str(manifest_doc.get("package_sha256", "")).removeprefix("sha256:") != sha(source_zip):
        raise AssertionError("baseline package hash mismatch")
    if (str(manifest_doc.get("package_entries_hash", "")).removeprefix("sha256:")
            != str(baseline.get("package_entries_hash", "")).removeprefix("sha256:")):
        raise AssertionError("baseline package entries hash mismatch")
    if manifest_doc.get("inclusion_manifest") != baseline.get("entries"):
        raise AssertionError("baseline inclusion manifest mismatch")
    tampered = case.root / "tampered_bundle.zip"
    with zipfile.ZipFile(source_zip) as src, zipfile.ZipFile(tampered, "w") as dst:
        for info in src.infolist():
            data = src.read(info)
            if info.filename.replace("\\", "/") == "README.md":
                data = data + b"\nZIP TAMPER\n"
            dst.writestr(info, data)
    inspection = canonical_delivery_manifest.inspect_zip_entries(tampered)
    failures = []
    if str(manifest_doc.get("package_sha256", "")).removeprefix("sha256:") == sha(tampered):
        failures.append("package_sha256_not_detected")
    else:
        failures.append("package_sha256_mismatch")
    if (str(manifest_doc.get("package_entries_hash", "")).removeprefix("sha256:")
            == str(inspection.get("package_entries_hash", "")).removeprefix("sha256:")):
        failures.append("package_entries_hash_not_detected")
    else:
        failures.append("package_entries_hash_mismatch")
    if manifest_doc.get("inclusion_manifest") == inspection.get("entries"):
        failures.append("entry_manifest_not_detected")
    else:
        failures.append("package_entry_manifest_mismatch")
    if any(name.endswith("not_detected") for name in failures):
        raise AssertionError("tampered ZIP was not detected: " + json.dumps(failures))
    # The source manifest authorization itself is untouched; record that the ZIP
    # gate is the layer that rejects the changed package.
    if not (case.run / "release_authorization.json").is_file():
        raise AssertionError("fixture release authorization missing")
    return {"control_result": "REJECT", "failures": failures}


def p18(case):
    """The verifier must not require or contain private key material."""
    if PROTECTED.is_relative_to(case.workspace) or PROTECTED.is_relative_to(case.store.root):
        raise AssertionError("fixture fixture key is inside an agent-writable root")
    pem = PRIVATE_KEY_PATH.read_bytes()
    for base in (case.workspace, case.store.root):
        for path in base.rglob("*"):
            if path.is_file() and pem in path.read_bytes():
                raise AssertionError("private key material found in " + str(path))
    for module in (ROOT / "cgkn/state/release_authorization.py",
                   ROOT / "cgkn/state/provenance.py"):
        text = module.read_text(encoding="utf-8")
        for token in ("Ed25519PrivateKey", "load_pem_private_key", "PRIVATE KEY"):
            if token in text:
                raise AssertionError(f"{token} found in verifier module {module.name}")
    # A random signature cannot pass verification.
    doc = read(case.run / "release_authorization.json")
    doc["signature"]["value_b64"] = base64.b64encode(b"\x00" * 64).decode("ascii")
    write(case.run / "release_authorization.json", doc)
    forged_status, forged_error, _ = attempt(lambda: case.gate.delivery_sources(
        case.acceptance, case.workspace, case.manifest))
    if forged_status != "REJECT":
        raise AssertionError("random signature was accepted")
    # Restore the valid signed authorization for later checks.
    sign_case(case, manifest=case.manifest)
    return {"control_result": "REJECT", "forged_error": forged_error}


def p19(case):
    """Agent tampering with policy, anchor or verifier must not change adjudication."""
    # Put a permissive anchor and a forged release inside both writable roots.
    attacker = Ed25519PrivateKey.generate()
    attacker_public = attacker.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    fake_anchor = {
        "kind": "ReleaseTrustAnchor", "schema_version": "1",
        "authority_id": AUTHORITY_ID,
        "keys": {"attacker": {
            "algorithm": "ed25519",
            "public_key_b64": base64.b64encode(attacker_public).decode("ascii"),
            "principal": "attacker"}},
    }
    write(case.workspace / "trust_anchor.json", fake_anchor)
    write(case.run / "trust_anchor.json", fake_anchor)
    payload = build_payload(case)
    payload["signer"] = {"key_id": "attacker", "principal": "attacker"}
    forged = sign_payload(payload, key=attacker, key_id="attacker")
    write(case.run / "release_authorization.json", forged)
    bind_gate(case, anchor=ANCHOR_PATH)
    status, error, _ = attempt(lambda: case.gate.delivery_sources(
        case.acceptance, case.workspace, case.manifest))
    if status != "REJECT":
        raise AssertionError("forged policy/anchor changed the verdict")
    # The real verifier must still be the installed one, not workspace bytes.
    import cgkn.state.provenance as loaded
    if Path(loaded.__file__).resolve().is_relative_to(case.workspace):
        raise AssertionError("workspace verifier was imported")
    return {"control_result": "REJECT", "forged_error": error}


# --------------------------------------------------------------------------
# Normal-path and fail-closed controls.
# --------------------------------------------------------------------------

def n01(case):
    result = case.gate.delivery_sources(case.acceptance, case.workspace, case.manifest)
    if result.get("status") != "TRUSTED":
        raise AssertionError("baseline signed release was rejected")
    if result.get("release_authorization", {}).get("release_id") != "rel-m12-001":
        raise AssertionError("release metadata missing from trusted result")
    if len(result.get("source_origins", {})) != len(case.manifest):
        raise AssertionError("baseline did not cover every delivered file")


def n02(case):
    gate = ProvenanceGate(case.store, PID, RID)
    status, error, _ = attempt(lambda: gate.delivery_sources(
        case.acceptance, case.workspace, case.manifest))
    if status != "REJECT":
        raise AssertionError("missing trust anchor was accepted")
    return {"control_result": "REJECT", "error": error}


def n03(case):
    (case.run / "release_authorization.json").unlink(missing_ok=True)
    status, error, _ = attempt(lambda: case.gate.delivery_sources(
        case.acceptance, case.workspace, case.manifest))
    if status != "REJECT":
        raise AssertionError("missing signed authorization was accepted")
    return {"control_result": "REJECT", "error": error}


def n04(case):
    worker_manifest = {
        name: digest for name, digest in case.manifest.items()
        if any(doc.get("kind") == "ImportedWorkerSource" and doc.get("artifact") == name
               for _, doc in [(p, read(p)) for p in (case.run / "source_imports").glob("*.json")])
    }
    result = case.gate.delivery_sources(case.acceptance, case.workspace, worker_manifest)
    if result.get("status") != "TRUSTED":
        raise AssertionError("worker-only delivery regressed")


def n05(case):
    """Exercise the formal production-provenance path with the signed batch."""
    candidate = case.workspace
    document = production_candidate_provenance.produce_project_session(
        case.store, PID, RID, candidate_dir=candidate, commit_sha="fixture-commit",
        release_trust_anchor=ANCHOR_PATH,
        release_authorization=case.run / "release_authorization.json")
    reference = Path(document["provenance_ref"])
    inspected = production_candidate_provenance.inspect(
        reference, expected_candidate_dir=candidate,
        release_trust_anchor=ANCHOR_PATH,
        release_authorization=case.run / "release_authorization.json")
    if inspected.get("status") != "PASS":
        raise AssertionError("formal production provenance path failed: " +
                             json.dumps(inspected.get("failures"), ensure_ascii=False))


CASES = [
    ("P01", "agent source without authorization", "REJECT", p01),
    ("P02", "modify authorized agent source", "REJECT", p02),
    ("P03", "agent source impersonates Worker", "REJECT", p03),
    ("P04", "B11 independent observation false", "REJECT", p04),
    ("P05", "invalid Worker receipt hash", "REJECT", p05),
    ("P06", "delivered file hash mismatch", "REJECT", p06),
    ("P07", "replay old candidate hash", "REJECT", p07),
    ("P08", "missing B10 evidence", "REJECT", p08),
    ("P09", "unrelated production_provenance_ref", "REJECT", p09),
    ("P10", "valid Agent source, authorization, reviews", "ACCEPT", p10),
    ("P11", "self-registration after changing README", "REJECT", p11),
    ("P12", "rewrite signed authorization bytes", "REJECT", p12),
    ("P13", "replace public key / policy", "REJECT", p13),
    ("P14", "change reviewed content with main.py unchanged", "REJECT", p14),
    ("P15", "rewrite B11 and recompute ordinary hashes", "REJECT", p15),
    ("P16", "replay another candidate's authorization", "REJECT", p16),
    ("P17", "change ZIP bytes with old manifest", "REJECT", p17),
    ("P18", "private key outside agent-writable roots", "REJECT", p18),
    ("P19", "agent changes policy/anchor/verifier", "REJECT", p19),
    ("N01", "valid signed batch still accepted", "ACCEPT", n01),
    ("N02", "no trust anchor fails closed", "REJECT", n02),
    ("N03", "missing signed authorization fails closed", "REJECT", n03),
    ("N04", "worker-only delivery compatibility", "ACCEPT", n04),
    ("N05", "formal production provenance path", "ACCEPT", n05),
]


def main():
    control_tests = {"P09", "P13", "P14", "P16", "P17", "P18", "P19", "N02", "N03"}
    results = []
    for test_id, description, expected, fn in CASES:
        case = None
        try:
            case = make_case(test_id.lower())
            if test_id not in {"N02", "N03"}:
                release_id = ("rel-m12-001" if test_id in {
                    "P01", "P02", "P03", "P04", "P05", "P06", "P07", "P08",
                    "P09", "P10", "N01", "N05"} else "rel-" + test_id.lower())
                sign_case(case, manifest=case.manifest, release_id=release_id)
            status, error, payload = attempt(lambda: fn(case))
            if test_id in control_tests:
                if status == "REJECT":
                    status = "ERROR"
                elif isinstance(payload, dict) and payload.get("control_result"):
                    status = payload["control_result"]
                else:
                    status = "ERROR"
        except Exception as exc:  # harness/environment failure
            status, error = "ERROR", f"{type(exc).__name__}: {str(exc)[:700]}"
        verdict = "PASS" if status == expected else "FAIL"
        results.append({
            "test_id": test_id,
            "description": description,
            "expected_result": expected,
            "actual_result": status,
            "error": error,
            "verdict": verdict,
            "temp_case": str(case.root) if case else None,
        })
        print(test_id, expected, status, verdict, (error or "")[:180])

    summary = {
        "kind": "P11FixIsolatedSecurityTests",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "scope": "isolated copies; no formal source or delivery artifact modified",
        "fixture_private_key": str(PRIVATE_KEY_PATH),
        "trust_anchor": str(ANCHOR_PATH),
        "results": results,
        "passed": sum(row["verdict"] == "PASS" for row in results),
        "total": len(results),
        "exit_code": 0 if all(row["verdict"] == "PASS" for row in results) else 1,
        "security_status": "IMPLEMENTED_NOT_TRUSTED",
        "reason": "Fixture key/anchor; no OS-isolated external signer is deployed.",
    }
    evidence = ROOT / "P11_P19_RESULTS.json"
    write(evidence, summary)
    print(json.dumps({"passed": summary["passed"], "total": summary["total"],
                      "exit_code": summary["exit_code"],
                      "evidence": str(evidence)}, ensure_ascii=False))
    raise SystemExit(summary["exit_code"])


if __name__ == "__main__":
    main()
