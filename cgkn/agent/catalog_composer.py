from __future__ import annotations

import copy
from typing import Any

from .composer import AGENT_SCHEMA, AgentComposer


SIMPLE_AGENT_SCHEMA = copy.deepcopy(AGENT_SCHEMA)
SIMPLE_AGENT_SCHEMA["properties"]["edits"]["items"].pop("allOf", None)


class CatalogAgentComposer(AgentComposer):
    """AgentComposer that fills registered capability contracts mechanically.

    The Planner still chooses the capability, parent, dependencies and any
    semantic config overrides. The Host supplies the immutable executor and
    leaf-contract boilerplate from the same catalog the Planner sees. This
    removes copy errors without moving planning or business decisions out of
    the model.
    """

    decision_schema = SIMPLE_AGENT_SCHEMA

    def __init__(self, *args: Any, root_config: dict[str, Any] | None = None,
                 **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.root_config = dict(root_config or {})
        self.additional_instructions = (
            (self.additional_instructions or "")
            + "\nFor add_node, return capability_ref, parent_id, depends_on and an optional "
              "config override object. The Host injects the registered executor_ref and "
              "leaf_contract from capability_catalog; do not reproduce those fields. "
              "For update_config, return only the changed config keys; the Host merges them "
              "onto the current node config."
        )

    @staticmethod
    def _catalog_for(context: Any, capability: str) -> dict[str, Any]:
        catalog = context.capability_catalog
        try:
            entry = catalog[capability]
        except (KeyError, TypeError) as exc:
            raise ValueError("capability is not registered in the current catalog: " + capability) from exc
        if not isinstance(entry, dict):
            raise ValueError("capability catalog entry must be an object")
        return dict(entry)

    def _normalize_decision(self, value: Any, context: Any) -> Any:
        if not isinstance(value, dict):
            return value
        edits = value.get("edits")
        if not isinstance(edits, list):
            return value
        normalized = []
        for raw in edits:
            if not isinstance(raw, dict):
                normalized.append(raw)
                continue
            edit = dict(raw)
            payload = edit.get("payload")
            if not isinstance(payload, dict):
                normalized.append(raw)
                continue
            payload = dict(payload)
            operation = edit.get("operation")
            if operation == "add_node":
                capability = str(payload.get("capability_ref", ""))
                if capability == "":
                    payload["config"] = {**self.root_config,
                                         **(payload.get("config") or {})}
                    normalized.append({**edit, "payload": payload})
                    continue
                entry = CatalogAgentComposer._catalog_for(context, capability)
                overrides = payload.get("config") or {}
                if not isinstance(overrides, dict):
                    raise ValueError("add_node config override must be an object")
                merged = dict(entry.get("config") or {})
                merged.update(overrides)
                merged["executor_ref"] = entry["executor_ref"]
                if "leaf_contract" not in merged:
                    raise ValueError("capability catalog entry has no leaf contract")
                contract = dict(merged["leaf_contract"])
                # The Planner owns depends_on. Keep the mechanical contract's
                # dependency identity equal to the node's real dependencies so
                # the catalog boilerplate cannot silently override planning.
                contract["dependencies"] = list(payload.get("depends_on") or [])
                merged["leaf_contract"] = contract
                payload["config"] = merged
            elif operation == "update_config":
                node_id = str(payload.get("node_id", ""))
                node = context.tree.by_id.get(node_id)
                if node is None:
                    raise ValueError("update_config references an unknown node: " + node_id)
                overrides = payload.get("config") or {}
                if not isinstance(overrides, dict):
                    raise ValueError("update_config config must be an object")
                current = dict(node.config)
                protected = {"executor_ref", "leaf_contract"}
                if protected.intersection(overrides):
                    raise ValueError("update_config cannot replace executor or leaf contract")
                payload["config"] = {**current, **overrides}
                payload = {"config": payload["config"]}
            normalized.append({**edit, "payload": payload})
        return {**value, "edits": normalized}


__all__ = ["CatalogAgentComposer"]
