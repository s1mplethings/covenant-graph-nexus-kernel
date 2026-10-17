from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import tempfile
from typing import Iterable

from .models import ConfigurationError, ProviderConfig


SCHEMA_VERSION = 1


class ProviderConfigStore:
    """Atomic metadata-only provider configuration storage."""

    def __init__(self, path: Path | str | None = None) -> None:
        self.path = Path(path) if path is not None else default_config_path()

    def load(self) -> list[ProviderConfig]:
        if not self.path.exists():
            return []
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ConfigurationError(f"cannot read provider config: {exc}") from exc
        if not isinstance(raw, dict):
            raise ConfigurationError("provider config root must be an object")
        if raw.get("schema_version") != SCHEMA_VERSION:
            raise ConfigurationError("unsupported provider config schema_version")
        entries = raw.get("providers")
        if not isinstance(entries, list):
            raise ConfigurationError("providers must be a list")
        providers = [ProviderConfig.from_dict(item) for item in entries]
        ids = [provider.provider_id for provider in providers]
        if len(ids) != len(set(ids)):
            raise ConfigurationError("provider_id values must be unique")
        return sorted(providers, key=lambda item: item.provider_id)

    def save(self, providers: Iterable[ProviderConfig]) -> None:
        ordered = sorted(list(providers), key=lambda item: item.provider_id)
        ids = [provider.provider_id for provider in ordered]
        if len(ids) != len(set(ids)):
            raise ConfigurationError("provider_id values must be unique")
        payload = {
            "schema_version": SCHEMA_VERSION,
            "providers": [provider.to_dict() for provider in ordered],
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        encoded = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        temp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=self.path.parent,
                prefix=f".{self.path.name}.",
                suffix=".tmp",
                delete=False,
            ) as handle:
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
                temp_path = Path(handle.name)
            try:
                temp_path.chmod(0o600)
            except OSError:
                pass
            os.replace(temp_path, self.path)
            try:
                self.path.chmod(0o600)
            except OSError:
                pass
        finally:
            if temp_path is not None and temp_path.exists():
                temp_path.unlink(missing_ok=True)


def default_config_path() -> Path:
    override = os.environ.get("CGKN_PROVIDER_LAB_CONFIG")
    if override:
        return Path(override).expanduser()
    if sys.platform == "win32":
        root = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
        return root / "CGKN" / "ProviderApiLab" / "providers.json"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "CGKN" / "ProviderApiLab" / "providers.json"
    root = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return root / "cgkn" / "provider-api-lab" / "providers.json"
