from __future__ import annotations

from dataclasses import dataclass
import os
from threading import RLock
from typing import Protocol

from .models import ProviderConfig


KEYRING_SERVICE = "cgkn.provider-api-lab"


class SecretError(RuntimeError):
    """Base class for credential resolution failures."""


class SecretUnavailable(SecretError):
    """The selected credential reference has no available value."""


class SecretBackendUnavailable(SecretError):
    """The requested credential backend cannot be used on this machine."""


class SecretStore(Protocol):
    def get(self, reference: str) -> str | None: ...
    def set(self, reference: str, value: str) -> None: ...
    def delete(self, reference: str) -> None: ...


class MemorySecretStore:
    def __init__(self) -> None:
        self._values: dict[str, str] = {}
        self._lock = RLock()

    def get(self, reference: str) -> str | None:
        with self._lock:
            return self._values.get(reference)

    def set(self, reference: str, value: str) -> None:
        value = value.strip()
        if not value:
            raise SecretError("credential value cannot be empty")
        with self._lock:
            self._values[reference] = value

    def delete(self, reference: str) -> None:
        with self._lock:
            self._values.pop(reference, None)


class EnvironmentSecretStore:
    def get(self, reference: str) -> str | None:
        return os.environ.get(reference) or None

    def set(self, reference: str, value: str) -> None:
        raise SecretError("environment credentials must be configured outside the application")

    def delete(self, reference: str) -> None:
        return None


class KeyringSecretStore:
    def _keyring(self):
        try:
            import keyring  # type: ignore[import-not-found]
        except ImportError as exc:
            raise SecretBackendUnavailable(
                "keyring is not installed; install the extension with the [keyring] extra"
            ) from exc
        return keyring

    def get(self, reference: str) -> str | None:
        try:
            return self._keyring().get_password(KEYRING_SERVICE, reference)
        except Exception as exc:  # keyring backends expose platform-specific errors
            raise SecretBackendUnavailable("system credential store is unavailable") from exc

    def set(self, reference: str, value: str) -> None:
        value = value.strip()
        if not value:
            raise SecretError("credential value cannot be empty")
        try:
            self._keyring().set_password(KEYRING_SERVICE, reference, value)
        except Exception as exc:
            raise SecretBackendUnavailable("could not write to system credential store") from exc

    def delete(self, reference: str) -> None:
        try:
            keyring = self._keyring()
            try:
                keyring.delete_password(KEYRING_SERVICE, reference)
            except keyring.errors.PasswordDeleteError:
                return
        except SecretBackendUnavailable:
            raise
        except Exception as exc:
            raise SecretBackendUnavailable("could not delete from system credential store") from exc


@dataclass(slots=True)
class SecretManager:
    memory: MemorySecretStore
    environment: EnvironmentSecretStore
    keyring: KeyringSecretStore

    @classmethod
    def create_default(cls) -> "SecretManager":
        return cls(
            memory=MemorySecretStore(),
            environment=EnvironmentSecretStore(),
            keyring=KeyringSecretStore(),
        )

    def _store_for(self, backend: str) -> SecretStore:
        if backend == "session":
            return self.memory
        if backend == "environment":
            return self.environment
        if backend == "keyring":
            return self.keyring
        raise SecretError(f"backend {backend!r} does not store credentials")

    def resolve(self, provider: ProviderConfig) -> str:
        if provider.secret_backend == "none":
            return ""
        value = self._store_for(provider.secret_backend).get(provider.secret_ref)
        if not value:
            raise SecretUnavailable(
                f"credential is unavailable for {provider.display_name} ({provider.secret_backend}:{provider.secret_ref})"
            )
        return value

    def set_for_provider(self, provider: ProviderConfig, value: str) -> None:
        if provider.secret_backend in {"none", "environment"}:
            if value.strip():
                raise SecretError(
                    "this backend does not accept credential values in the GUI"
                )
            return
        self._store_for(provider.secret_backend).set(provider.secret_ref, value)

    def delete_for_provider(self, provider: ProviderConfig) -> None:
        if provider.secret_backend in {"session", "keyring"}:
            self._store_for(provider.secret_backend).delete(provider.secret_ref)

    def status(self, provider: ProviderConfig) -> str:
        if provider.secret_backend == "none":
            return "not required"
        try:
            value = self._store_for(provider.secret_backend).get(provider.secret_ref)
        except SecretBackendUnavailable:
            return "backend unavailable"
        return "available" if value else "missing"
