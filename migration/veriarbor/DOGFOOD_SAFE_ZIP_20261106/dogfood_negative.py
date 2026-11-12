import json
from pathlib import Path
import dogfood_certificate as d
from veriarbor.block import Block
from veriarbor.variant import Variant
from veriarbor.certificate import can_substitute

tampered = Variant("safe-zip-v1-tampered", (("safe_zip_path.py", "sha256:" + "0" * 64),), "VERIFIED")
tampered_block = Block("SAFE_ZIP", "Safe ZIP entry normalization", (d.in_v1,), (d.out,), d.effects,
                       (tampered,), tampered.variant_id)
match = d.cert.matches(tampered_block, {"independent": d.checker_hash}, evidence_authenticated=True)
substitute = can_substitute(d.cert, tampered_block, replacement_certificate=d.cert,
                            checkers={"independent": d.checker_hash}, evidence_authenticated=True)
assert match is False
assert substitute is False
result = {
    "kind": "VeriArborDogfoodNegativeControl",
    "status": "PASS",
    "tampered_certificate_matches": match,
    "tampered_can_substitute": substitute,
    "expected": "both False",
}
Path(__file__).with_name("DOGFOOD_NEGATIVE.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf8")
print(json.dumps(result, ensure_ascii=False, indent=2))
