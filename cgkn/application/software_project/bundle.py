from __future__ import annotations

from dataclasses import dataclass

from cgkn.capabilities import CapabilityDescriptor, CapabilityLifecycle
from cgkn.component import ComponentSpec, PortSpec


CAPABILITY_EXECUTORS = {
    "workspace.inspect@1": "local.file@1",
    "project.file.generate@1": "llm.cheap@1",
    "project.file.patch@1": "llm.cheap@1",
    "project.tests.generate@1": "llm.cheap@1",
    "project.python.compile@1": "local.command@1",
    "project.python.pytest@1": "local.python-test@1",
    "project.command.smoke@1": "local.command@1",
    "project.acceptance.external@1": "project.acceptance@1",
    "project.snapshot@1": "project.snapshot@1",
}


@dataclass(frozen=True)
class SoftwareProjectBundle:
    components: tuple[ComponentSpec, ...]
    capabilities: tuple[CapabilityDescriptor, ...]

    @classmethod
    def build(cls) -> "SoftwareProjectBundle":
        components: list[ComponentSpec] = []
        capabilities: list[CapabilityDescriptor] = []
        for ref, executor_ref in CAPABILITY_EXECUTORS.items():
            capability_id, version = ref.rsplit("@", 1)
            inputs = (PortSpec("request", "artifact.project_request@1", required=False),)
            outputs = (PortSpec("result", "artifact.project_result@1"),)
            component = ComponentSpec(capability_id, version, inputs, outputs, {"bounded": True}, "policy.software_project@1", {"layer": "L6"})
            components.append(component)
            effects = ("filesystem.read",) if ref == "workspace.inspect@1" else ("filesystem.write",) if ".file." in ref or ".tests." in ref else ("process.execute",) if ref in {"project.python.compile@1", "project.python.pytest@1", "project.command.smoke@1", "project.acceptance.external@1"} else ("filesystem.read",)
            capabilities.append(CapabilityDescriptor(
                capability_id, version, component.ref, executor_ref, ("deterministic", "llm"),
                ("request",), ("result",), effects, 120.0, "bounded", "MEDIUM" if "llm" in executor_ref else "LOW",
                "cgkn.application.software_project", {"implementation_identity": executor_ref},
                ("tests/application/software_project",), CapabilityLifecycle.ADMITTED,
            ))
        return cls(tuple(components), tuple(capabilities))

    @property
    def catalog(self) -> dict[str, dict[str, object]]:
        return {
            item.ref: {
                "executor_ref": item.executor_ref,
                "allowed_effects": list(item.declared_effects),
                "timeout_seconds": item.timeout_seconds,
                "rule": "one primary target file per worker node; two only when explicitly declared and tightly coupled",
            }
            for item in self.capabilities
        }

    @property
    def known_capabilities(self) -> set[str]:
        return {item.ref for item in self.capabilities}
