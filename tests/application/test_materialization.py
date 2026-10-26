import json
from dataclasses import dataclass

from cgkn.application.materialization import materialize_json
from cgkn.application.requirements.obligation import FrozenMapping


@dataclass(frozen=True)
class NestedEvidence:
    name: str
    rows: tuple[FrozenMapping, ...]


def test_nested_immutable_dataclass_materializes_to_json_primitives() -> None:
    value = {"outer": (NestedEvidence("oracle", (FrozenMapping({"status": "PASS", "details": (1, 2)}),)),)}
    result = materialize_json(value)
    assert result == {"outer": [{"name": "oracle", "rows": [{"details": [1, 2], "status": "PASS"}]}]}
    assert json.loads(json.dumps(result)) == result
