from __future__ import annotations

import re
from dataclasses import dataclass

REF_RE = re.compile(r"^(artifact|module|flow|policy|proposal|migration)\.[a-z0-9_.-]+@[A-Za-z0-9_.-]+$")
PARTS_RE = re.compile(r"^(?P<kind>artifact|module|flow|policy|proposal|migration)\.(?P<name>[a-z0-9_.-]+)@(?P<version>[A-Za-z0-9_.-]+)$")


@dataclass(frozen=True)
class ContractRef:
    kind: str
    name: str
    version: str

    @property
    def id(self) -> str:
        return f"{self.kind}.{self.name}"

    def __str__(self) -> str:
        return f"{self.id}@{self.version}"


def parse_ref(value: str) -> ContractRef:
    match = PARTS_RE.match(value)
    if not match:
        raise ValueError(f"Invalid CGNK ref: {value}")
    return ContractRef(match.group("kind"), match.group("name"), match.group("version"))


def is_valid_ref(value: str, kind: str | None = None) -> bool:
    match = PARTS_RE.match(value)
    if not match:
        return False
    return kind is None or match.group("kind") == kind


def ref_of(doc: dict) -> str:
    return f"{doc['id']}@{doc['version']}"
