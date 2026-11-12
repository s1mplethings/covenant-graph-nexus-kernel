# VeriArbor signed release authorization (P11 fix)

## 1. What this changes

Before the fix, `AuthorizedAgentSource` was authorized by ordinary JSON in the
agent-writable run store:

- `authorized_by: "user"` was only a string.
- `AuthorizedAgentSourceAuthorization`, `AuthorizedAgentSourceReview`,
  `B10_CERTIFICATE.json` and `B11_ACCEPTANCE.json` were all writable by the
  same process that could change the delivered bytes.
- `_authorized_agent_origin` checked only `main.py`'s hash in B10, not the
  `relevant_section_hashes` of README, TEST_PLAN or the test file.

P11 proved the bypass: change `README.md`, rewrite the authorization and review
JSON, update `source_imports`, and `delivery_sources` accepted the new bytes.

The fix adds one batch-scoped Ed25519-signed release authorization.  The
verifier checks the signature against a public-key trust anchor that must live
outside the run store and the candidate workspace.  It also pins:

- release id, logical task id, scope, nonce and validity window;
- the exact delivery manifest (every path + SHA-256);
- the real `author_type` for every artifact;
- the exact `authorization_ref`, `review_ref`, `B10` and `B11` document hashes;
- B10 `relevant_section_hashes["<artifact>#full"]` for every artifact B10
  actually certifies.

An agent with run-store and workspace write access can still corrupt files, but
it cannot produce a new valid signature.  A missing anchor or missing signed
authorization fails closed with `PENDING_TRUST_ANCHOR`.

## 2. What the signature does and does not prove

The signature proves only:

> the holder of the private key authorized this exact manifest and these exact
> evidence hashes.

It does **not** prove:

- that the host actually protected the private key;
- that the signer independently re-ran B10/B11 instead of trusting agent-written
  JSON;
- that the same Windows user cannot read the signer directory or call the
  signer process.

If the agent and the controller run as the same Windows user, with write access
to the same files and can execute the signer, there is **no strong isolation**.
In that case the status is `PENDING_TRUST_ANCHOR`, not a production security
PASS.

## 3. Trust anchor and authorization formats

Trust anchor (public keys only; must be outside the store and workspace):

```json
{
  "kind": "ReleaseTrustAnchor",
  "schema_version": "1",
  "authority_id": "veriarbor-release-authority",
  "keys": {
    "release-2026-11": {
      "algorithm": "ed25519",
      "public_key_b64": "...",
      "principal": "user",
      "purpose": "final_delivery_source_authorization"
    }
  }
}
```

Release authorization (may live in the run store; its bytes are signed):

```json
{
  "kind": "SignedReleaseAuthorization",
  "schema_version": "1",
  "authority_id": "veriarbor-release-authority",
  "release_id": "m12-final-20261106",
  "logical_task_id": "iter132-promotion-studio/final-validation-01",
  "scope": "final_delivery_source_manifest",
  "not_before": "2026-11-06T00:00:00+00:00",
  "expires_at": "2026-12-06T00:00:00+00:00",
  "nonce": "<at least 32 hex chars>",
  "candidate_source_manifest_sha256": "<sha256 of the canonical manifest>",
  "artifacts": {
    "README.md": {
      "sha256": "<delivered bytes>",
      "author_type": "agent",
      "author_identity": "DeepSeek V4.1 Flash 1017 (OpenCode agent)",
      "authorization_sha256": "<AuthorizedAgentSourceAuthorization file>",
      "review_sha256": "<AuthorizedAgentSourceReview file>",
      "b10_certificate_sha256": "<B10 certificate file>",
      "b11_acceptance_sha256": "<B11 acceptance file>",
      "b10_section_sha256": "<B10 relevant_section_hashes['README.md#full'] or null>"
    },
    "worker_file.py": {
      "sha256": "<delivered bytes>",
      "author_type": "worker",
      "receipt_sha256": "<Worker receipt file>",
      "source_project_id": "...",
      "source_run_id": "..."
    }
  },
  "signer": {"key_id": "release-2026-11", "principal": "user"},
  "signature": {
    "algorithm": "ed25519",
    "key_id": "release-2026-11",
    "value_b64": "..."
  }
}
```

## 4. Deployment steps (controller / user side)

1. Create a separate signing account, HSM, or at minimum an ACL-protected
   directory that the agent cannot read or execute.  Do **not** put the private
   key in the run store, the candidate workspace, an environment variable, or a
   script the agent can invoke.
2. Generate an Ed25519 key pair in that environment:
   ```powershell
   python -c "from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey; from cryptography.hazmat.primitives import serialization; k=Ed25519PrivateKey.generate(); open(r'C:\protected\release-private.pem','wb').write(k.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))"
   ```
3. Re-run the independent B10/B11 checks in the signing environment.  The signer
   tool must not merely hash agent-written review JSON.
4. Sign the delivery batch:
   ```powershell
   python tools/sign_release_authorization.py ^
     --run-store <FileRunStore root> ^
     --run-relative iter132-promotion-studio/final-validation-01 ^
     --manifest <delivery-manifest-json> ^
     --release-id m12-final-20261106 ^
     --logical-task-id iter132-promotion-studio/final-validation-01 ^
     --private-key C:\protected\release-private.pem ^
     --key-id release-2026-11 ^
     --anchor-out C:\protected\release-trust-anchor.json ^
     --out <run>/release_authorization.json ^
     --not-before ... --expires-at ... --nonce ...
   ```
5. Pass the trusted context to the formal gate:
   ```python
   from scripts import final_delivery_truth
   result = final_delivery_truth.evaluate(
       project_dir,
       manifest,
       production_provenance_ref=provenance_ref,
       release_trust_anchor=r"C:\protected\release-trust-anchor.json",
       release_authorization=r"...\release_authorization.json",
   )
   ```
   `final_delivery_truth.evaluate` forwards the context to
   `production_candidate_provenance.configure_release_trust`; the public gate's
   `production_candidate_provenance.inspect` calls then use it.
6. Verify P01-P19 with the fixture key.  The fixture key must never sign a
   formal delivery.

## 5. Rollback / fail-closed behavior

- No anchor: `PENDING_TRUST_ANCHOR`.
- Anchor inside the run store or workspace: `INVALID_PROVENANCE`.
- Missing signed authorization: `PENDING_TRUST_ANCHOR`.
- Wrong signer key, bad signature, expired window, different logical task,
  different manifest, changed artifact hash, changed review/B10/B11 hash:
  `INVALID_PROVENANCE`.
- Worker-only deliveries keep the original Worker receipt requirements and do
  not need an agent release authorization.
- The existing `FINAL_DELIVERY_SECURITY_HOLD.json` is not removed by this
  patch.  Recognition stays paused until a real external signer is deployed
  and a new signed release is produced.
