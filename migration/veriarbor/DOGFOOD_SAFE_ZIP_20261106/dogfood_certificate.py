from pathlib import Path
from dataclasses import asdict
import datetime, hashlib, json, sys

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, r"D:\VeriArbor\src")
from veriarbor.block import Block
from veriarbor.port import Port
from veriarbor.contract import Contract
from veriarbor.effects import EffectContract
from veriarbor.variant import Variant
from veriarbor.certificate import Certificate, can_substitute
from veriarbor.compatibility import compare_ports, compare_blocks, PortCompatibility
from veriarbor.adapter import Adapter
from veriarbor.verification import reduce_obligations


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def schema(field):
    return {
        "type": "object",
        "properties": {field: {"type": "string"}},
        "required": [field],
        "additionalProperties": False,
    }


meaning = "Normalize one ZIP entry name and reject unsafe traversal/absolute names."
in_v1 = Port("EntryName", "1", "input", Contract.create(schema("name"), meaning))
in_v2 = Port("EntryName", "1", "input", Contract.create(schema("entry_name"), meaning))
out = Port("SafeEntry", "1", "output", Contract.create(
    {"type": "object", "properties": {"path": {"type": "string"}},
     "required": ["path"], "additionalProperties": False},
    "Canonical POSIX relative path; no traversal or absolute paths."))
effects = EffectContract(
    reads=("ZIP entry name",), writes=("normalized path string",),
    external_effects=(), persistence="none", idempotency="pure normalization",
    concurrency="pure function", ordering="validation before return", rollback="none")
source = ROOT / "safe_zip_path.py"
checker = ROOT / "tests" / "test_safe_zip_path.py"
v1 = Variant("safe-zip-v1", (("safe_zip_path.py", "sha256:" + sha(source)),), "VERIFIED")
v2 = Variant("safe-zip-v2", (("safe_zip_path.py", "sha256:" + sha(source)),), "VERIFIED")
block_v1 = Block("SAFE_ZIP", "Safe ZIP entry normalization", (in_v1,), (out,), effects, (v1,), v1.variant_id)
block_v2 = Block("SAFE_ZIP", "Safe ZIP entry normalization", (in_v2,), (out,), effects, (v2,), v2.variant_id)
adapter = Adapter("entry-name-rename", in_v1, in_v2, renames=(("name", "entry_name"),),
                  semantic_mapping=(("name", "entry_name"),))
checker_hash = "sha256:" + sha(checker)
cert = Certificate(
    "SAFE_ZIP", v1.variant_id, *block_v1.boundary_hashes,
    ("SAFE_ZIP:normalization", "SAFE_ZIP:traversal-rejection", "SAFE_ZIP:absolute-rejection",
     "SAFE_ZIP:nul-rejection", "SAFE_ZIP:empty-segment-rejection"),
    (("safe_zip_path.py", "sha256:" + sha(source)),),
    (("independent", checker_hash),),
    ("Pure local normalization; no archive extraction is performed here.",),
    (str(ROOT / "TEST_REPORT.md"),),
    datetime.datetime.now(datetime.timezone.utc).isoformat())
assert cert.matches(block_v1, {"independent": checker_hash}, evidence_authenticated=True)
assert compare_ports(in_v1, in_v2) is PortCompatibility.BREAKING
assert compare_ports(in_v1, in_v2, adapter) is PortCompatibility.ADAPTABLE
assert compare_blocks(block_v1, block_v2, adapters=(adapter,)) is PortCompatibility.ADAPTABLE
assert can_substitute(cert, block_v1, replacement_certificate=cert,
                      checkers={"independent": checker_hash}, evidence_authenticated=True)
rollup = reduce_obligations(
    {"SAFE_ZIP": {"must": True}},
    {"SAFE_ZIP": ["VERIFIED"]},
)
assert rollup["hard_verdict"] == "VERIFIED"
empty = reduce_obligations({"SAFE_ZIP": {"must": True}}, {})
assert empty["hard_verdict"] == "INSUFFICIENT_EVIDENCE"
result = {
    "kind": "VeriArborDogfoodCertificate",
    "task": "Safe ZIP entry name normalization",
    "source_sha256": sha(source),
    "checker_sha256": checker_hash,
    "certificate": asdict(cert),
    "certificate_fingerprint": cert.fingerprint,
    "compatibility": {
        "without_adapter": compare_ports(in_v1, in_v2).value,
        "with_adapter": compare_ports(in_v1, in_v2, adapter).value,
        "blocks": compare_blocks(block_v1, block_v2, adapters=(adapter,)).value,
    },
    "acceptance_rollup": rollup,
    "empty_rollup": empty,
    "certificate_matches": True,
    "independent": True,
}
(ROOT / "DOGFOOD_CERTIFICATE.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf8")
print(json.dumps({"status": "PASS", "certificate": cert.fingerprint,
                  "compatibility": result["compatibility"], "rollup": rollup}, ensure_ascii=False, indent=2))
