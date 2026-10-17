from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Any, Mapping
from urllib.parse import urlparse


_PROVIDER_ID = re.compile(r"^[a-z][a-z0-9_-]{1,63}$")
_ENV_REF = re.compile(r"^[A-Z_][A-Z0-9_]{1,127}$")
_ALLOWED_SECRET_BACKENDS = frozenset({"none", "session", "environment", "keyring"})
_ALLOWED_ADAPTERS = frozenset({"openai_chat"})
_ALLOWED_AUTH_HEADERS = frozenset({"Authorization", "api-key", "x-api-key"})
_ALLOWED_AUTH_PREFIXES = frozenset({"", "Bearer "})
_FORBIDDEN_CONFIG_FIELDS = frozenset(
    {
        "api_key",
        "apikey",
        "access_token",
        "bearer_token",
        "credential",
        "credentials",
        "password",
        "secret",
        "token",
    }
)


class ConfigurationError(ValueError):
    """Raised when provider metadata violates the local security contract."""


def _clean_text(value: object, field_name: str, *, required: bool = True) -> str:
    if not isinstance(value, str):
        raise ConfigurationError(f"{field_name} must be a string")
    result = value.strip()
    if required and not result:
        raise ConfigurationError(f"{field_name} is required")
    return result


def _validate_base_url(base_url: str) -> str:
    parsed = urlparse(base_url)
    if parsed.scheme not in {"https", "http"} or not parsed.hostname:
        raise ConfigurationError("base_url must be an absolute HTTP(S) URL")
    if parsed.username or parsed.password:
        raise ConfigurationError("base_url must not contain embedded credentials")
    if parsed.query or parsed.fragment:
        raise ConfigurationError("base_url must not contain a query or fragment")
    local_hosts = {"localhost", "127.0.0.1", "::1"}
    if parsed.scheme != "https" and parsed.hostname not in local_hosts:
        raise ConfigurationError("non-local provider URLs must use HTTPS")
    return base_url.rstrip("/")


@dataclass(frozen=True, slots=True)
class ProviderConfig:
    provider_id: str
    display_name: str
    base_url: str
    model: str
    adapter: str = "openai_chat"
    secret_backend: str = "environment"
    secret_ref: str = ""
    auth_header: str = "Authorization"
    auth_prefix: str = "Bearer "
    timeout_seconds: float = 90.0

    def __post_init__(self) -> None:
        provider_id = _clean_text(self.provider_id, "provider_id").lower()
        if not _PROVIDER_ID.fullmatch(provider_id):
            raise ConfigurationError(
                "provider_id must start with a letter and contain only lowercase letters, digits, '_' or '-'"
            )
        display_name = _clean_text(self.display_name, "display_name")
        base_url = _validate_base_url(_clean_text(self.base_url, "base_url"))
        model = _clean_text(self.model, "model")
        adapter = _clean_text(self.adapter, "adapter")
        if adapter not in _ALLOWED_ADAPTERS:
            raise ConfigurationError(f"unsupported adapter: {adapter}")
        backend = _clean_text(self.secret_backend, "secret_backend")
        if backend not in _ALLOWED_SECRET_BACKENDS:
            raise ConfigurationError(f"unsupported secret backend: {backend}")
        secret_ref = _clean_text(self.secret_ref, "secret_ref", required=False)
        if backend == "environment" and not _ENV_REF.fullmatch(secret_ref):
            raise ConfigurationError(
                "environment secret_ref must be an uppercase environment variable name"
            )
        if backend in {"session", "keyring"}:
            if secret_ref and secret_ref != provider_id:
                raise ConfigurationError(
                    "session and keyring secret_ref must equal provider_id"
                )
            secret_ref = provider_id
        if backend == "none":
            secret_ref = ""
        auth_header = _clean_text(self.auth_header, "auth_header", required=backend != "none")
        if backend != "none" and auth_header not in _ALLOWED_AUTH_HEADERS:
            raise ConfigurationError("auth_header is not in the safe allowlist")
        if not isinstance(self.auth_prefix, str):
            raise ConfigurationError("auth_prefix must be a string")
        auth_prefix = self.auth_prefix
        if backend != "none" and auth_prefix not in _ALLOWED_AUTH_PREFIXES:
            raise ConfigurationError("auth_prefix is not in the safe allowlist")
        if backend == "none":
            auth_header = ""
            auth_prefix = ""
        try:
            timeout_seconds = float(self.timeout_seconds)
        except (TypeError, ValueError) as exc:
            raise ConfigurationError("timeout_seconds must be numeric") from exc
        if not 1.0 <= timeout_seconds <= 600.0:
            raise ConfigurationError("timeout_seconds must be between 1 and 600")

        object.__setattr__(self, "provider_id", provider_id)
        object.__setattr__(self, "display_name", display_name)
        object.__setattr__(self, "base_url", base_url)
        object.__setattr__(self, "model", model)
        object.__setattr__(self, "adapter", adapter)
        object.__setattr__(self, "secret_backend", backend)
        object.__setattr__(self, "secret_ref", secret_ref)
        object.__setattr__(self, "auth_header", auth_header)
        object.__setattr__(self, "auth_prefix", auth_prefix)
        object.__setattr__(self, "timeout_seconds", timeout_seconds)

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "ProviderConfig":
        if not isinstance(raw, Mapping):
            raise ConfigurationError("provider entry must be an object")
        lowered = {str(key).lower() for key in raw}
        forbidden = sorted(lowered & _FORBIDDEN_CONFIG_FIELDS)
        if forbidden:
            raise ConfigurationError(
                "plaintext credential fields are forbidden in provider configuration: "
                + ", ".join(forbidden)
            )
        allowed = {
            "provider_id",
            "display_name",
            "base_url",
            "model",
            "adapter",
            "secret_backend",
            "secret_ref",
            "auth_header",
            "auth_prefix",
            "timeout_seconds",
        }
        unknown = sorted(set(raw) - allowed)
        if unknown:
            raise ConfigurationError("unknown provider fields: " + ", ".join(unknown))
        return cls(**dict(raw))

    def to_dict(self) -> dict[str, Any]:
        """Return persistence metadata. This method can never return a credential value."""
        return {
            "provider_id": self.provider_id,
            "display_name": self.display_name,
            "base_url": self.base_url,
            "model": self.model,
            "adapter": self.adapter,
            "secret_backend": self.secret_backend,
            "secret_ref": self.secret_ref,
            "auth_header": self.auth_header,
            "auth_prefix": self.auth_prefix,
            "timeout_seconds": self.timeout_seconds,
        }

    def public_dict(self) -> dict[str, Any]:
        """Return export-safe metadata without credential location information."""
        return {
            "provider_id": self.provider_id,
            "display_name": self.display_name,
            "base_url": self.base_url,
            "model": self.model,
            "adapter": self.adapter,
            "timeout_seconds": self.timeout_seconds,
        }


@dataclass(frozen=True, slots=True)
class ComparisonOptions:
    temperature: float = 0.2
    max_tokens: int = 1024
    system_prompt: str = ""
    max_concurrency: int = 4

    def __post_init__(self) -> None:
        try:
            temperature = float(self.temperature)
        except (TypeError, ValueError) as exc:
            raise ConfigurationError("temperature must be numeric") from exc
        try:
            max_tokens = int(self.max_tokens)
            max_concurrency = int(self.max_concurrency)
        except (TypeError, ValueError) as exc:
            raise ConfigurationError("max_tokens and max_concurrency must be integers") from exc
        if not 0.0 <= temperature <= 2.0:
            raise ConfigurationError("temperature must be between 0 and 2")
        if not 1 <= max_tokens <= 131_072:
            raise ConfigurationError("max_tokens must be between 1 and 131072")
        if not 1 <= max_concurrency <= 16:
            raise ConfigurationError("max_concurrency must be between 1 and 16")
        object.__setattr__(self, "temperature", temperature)
        object.__setattr__(self, "max_tokens", max_tokens)
        object.__setattr__(self, "max_concurrency", max_concurrency)
        object.__setattr__(self, "system_prompt", str(self.system_prompt).strip())


@dataclass(frozen=True, slots=True)
class ProviderResult:
    provider_id: str
    display_name: str
    model: str
    status: str
    text: str = ""
    reasoning: str = ""
    error: str = ""
    latency_ms: int = 0
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None
    request_id: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider_id": self.provider_id,
            "display_name": self.display_name,
            "model": self.model,
            "status": self.status,
            "text": self.text,
            "reasoning": self.reasoning,
            "error": self.error,
            "latency_ms": self.latency_ms,
            "usage": {
                "prompt_tokens": self.prompt_tokens,
                "completion_tokens": self.completion_tokens,
                "total_tokens": self.total_tokens,
            },
            "request_id": self.request_id,
            "metadata": dict(self.metadata),
        }
