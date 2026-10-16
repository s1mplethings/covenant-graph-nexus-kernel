from __future__ import annotations

from typing import Any, Mapping, Protocol


class ArtifactAdapter(Protocol):
    design_id: str

    def create(self, kind: str, subject_ref: str, payload: Mapping[str, Any], *, producer_ref: str = "experiment", inputs: tuple[str, ...] = (), revision: int = 1) -> Any: ...
    def load(self, value: Mapping[str, Any]) -> Any: ...
    def as_dict(self, artifact: Any) -> dict[str, Any]: ...
    def validate_graph(self, artifacts: tuple[Any, ...], *, current_revisions: Mapping[str, int] | None = None) -> None: ...
    def complexity(self) -> Mapping[str, int]: ...


def get_design(design: str) -> ArtifactAdapter:
    key = design.strip().upper()
    if key == "A":
        from ..design_a import ADAPTER
        return ADAPTER
    if key == "B":
        from ..design_b import ADAPTER
        return ADAPTER
    if key == "C":
        from ..design_c import ADAPTER
        return ADAPTER
    raise ValueError(f"unknown design: {design}")
