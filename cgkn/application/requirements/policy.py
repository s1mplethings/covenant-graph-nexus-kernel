from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping


@dataclass(frozen=True)
class DependencyDomainPolicy:
    stdlib_only: bool = False
    allowed_packages: tuple[str, ...] = ()
    forbidden_packages: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        allowed = tuple(sorted(set(str(item) for item in self.allowed_packages)))
        forbidden = tuple(sorted(set(str(item) for item in self.forbidden_packages)))
        if set(allowed) & set(forbidden):
            raise ValueError("a package cannot be both allowed and forbidden")
        if self.stdlib_only and allowed:
            raise ValueError("stdlib_only cannot allow external packages")
        object.__setattr__(self, "allowed_packages", allowed)
        object.__setattr__(self, "forbidden_packages", forbidden)

    def as_dict(self) -> dict[str, Any]:
        return {"stdlib_only": self.stdlib_only, "allowed_packages": list(self.allowed_packages), "forbidden_packages": list(self.forbidden_packages)}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "DependencyDomainPolicy":
        return cls(bool(value.get("stdlib_only", False)), tuple(value.get("allowed_packages", ())), tuple(value.get("forbidden_packages", ())))


@dataclass(frozen=True)
class NetworkPolicy:
    outbound: str = "FORBIDDEN"

    def __post_init__(self) -> None:
        if self.outbound not in {"FORBIDDEN", "ALLOWLIST", "ALLOWED"}:
            raise ValueError("network outbound must be FORBIDDEN, ALLOWLIST, or ALLOWED")

    def as_dict(self) -> dict[str, Any]:
        return {"outbound": self.outbound}


@dataclass(frozen=True)
class DependencyPolicy:
    policy_id: str
    runtime: DependencyDomainPolicy = field(default_factory=DependencyDomainPolicy)
    development: DependencyDomainPolicy = field(default_factory=DependencyDomainPolicy)
    test: DependencyDomainPolicy = field(default_factory=DependencyDomainPolicy)
    tooling: DependencyDomainPolicy = field(default_factory=DependencyDomainPolicy)
    network: NetworkPolicy = field(default_factory=NetworkPolicy)
    schema_version: str = "1.0"

    def __post_init__(self) -> None:
        if not self.policy_id.strip():
            raise ValueError("dependency policy requires policy_id")

    def as_dict(self) -> dict[str, Any]:
        return {
            "policy_id": self.policy_id, "runtime": self.runtime.as_dict(), "development": self.development.as_dict(),
            "test": self.test.as_dict(), "tooling": self.tooling.as_dict(), "network": self.network.as_dict(),
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "DependencyPolicy":
        return cls(
            policy_id=str(value["policy_id"]), runtime=DependencyDomainPolicy.from_dict(value.get("runtime", {})),
            development=DependencyDomainPolicy.from_dict(value.get("development", {})),
            test=DependencyDomainPolicy.from_dict(value.get("test", {})),
            tooling=DependencyDomainPolicy.from_dict(value.get("tooling", {})),
            network=NetworkPolicy(str(value.get("network", {}).get("outbound", "FORBIDDEN"))),
            schema_version=str(value.get("schema_version", "1.0")),
        )

    def allows(self, domain: str, package: str) -> bool:
        policy = getattr(self, domain, None)
        if not isinstance(policy, DependencyDomainPolicy):
            raise ValueError(f"unknown dependency domain: {domain}")
        return not policy.stdlib_only and package in policy.allowed_packages and package not in policy.forbidden_packages
