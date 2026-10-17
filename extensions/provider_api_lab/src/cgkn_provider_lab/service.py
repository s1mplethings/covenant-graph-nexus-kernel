from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import os
from typing import Iterable, Mapping

from .adapters import ADAPTERS, Adapter
from .models import ComparisonOptions, ProviderConfig, ProviderResult
from .redaction import redact_text
from .secrets import SecretManager, SecretError


class ProviderComparisonService:
    def __init__(
        self,
        secret_manager: SecretManager | None = None,
        adapters: Mapping[str, Adapter] | None = None,
    ) -> None:
        self.secret_manager = secret_manager or SecretManager.create_default()
        self.adapters = dict(adapters or ADAPTERS)

    def invoke_one(
        self,
        provider: ProviderConfig,
        prompt: str,
        options: ComparisonOptions,
    ) -> ProviderResult:
        prompt = prompt.strip()
        if not prompt:
            raise ValueError("prompt cannot be empty")
        adapter = self.adapters.get(provider.adapter)
        if adapter is None:
            return ProviderResult(
                provider_id=provider.provider_id,
                display_name=provider.display_name,
                model=provider.model,
                status="error",
                error=f"adapter not registered: {provider.adapter}",
            )
        credential = ""
        try:
            credential = self.secret_manager.resolve(provider)
            return adapter.invoke(provider, credential, prompt, options)
        except SecretError as exc:
            return ProviderResult(
                provider_id=provider.provider_id,
                display_name=provider.display_name,
                model=provider.model,
                status="error",
                error=redact_text(exc, [credential]),
            )
        except Exception as exc:  # adapters are a plugin boundary; fail closed
            return ProviderResult(
                provider_id=provider.provider_id,
                display_name=provider.display_name,
                model=provider.model,
                status="error",
                error=redact_text(f"adapter failure: {exc}", [credential]),
            )

    def compare(
        self,
        providers: Iterable[ProviderConfig],
        prompt: str,
        options: ComparisonOptions | None = None,
    ) -> list[ProviderResult]:
        selected = list(providers)
        if not selected:
            raise ValueError("at least one provider must be selected")
        ids = [provider.provider_id for provider in selected]
        if len(ids) != len(set(ids)):
            raise ValueError("selected providers must have unique provider_id values")
        options = options or ComparisonOptions()
        results: dict[str, ProviderResult] = {}
        workers = min(options.max_concurrency, len(selected))
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="provider-lab") as executor:
            futures = {
                executor.submit(self.invoke_one, provider, prompt, options): provider.provider_id
                for provider in selected
            }
            for future in as_completed(futures):
                provider_id = futures[future]
                try:
                    results[provider_id] = future.result()
                except Exception as exc:
                    provider = next(item for item in selected if item.provider_id == provider_id)
                    results[provider_id] = ProviderResult(
                        provider_id=provider.provider_id,
                        display_name=provider.display_name,
                        model=provider.model,
                        status="error",
                        error=redact_text(f"worker failure: {exc}"),
                    )
        return [results[provider.provider_id] for provider in selected]

    def export_results(
        self,
        path: Path | str,
        providers: Iterable[ProviderConfig],
        prompt: str,
        options: ComparisonOptions,
        results: Iterable[ProviderResult],
    ) -> None:
        target = Path(path)
        provider_list = list(providers)
        result_list = list(results)
        known_secrets: list[str] = []
        for provider in provider_list:
            try:
                secret = self.secret_manager.resolve(provider)
            except SecretError:
                continue
            if secret:
                known_secrets.append(secret)

        payload = {
            "schema_version": 1,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "prompt": prompt,
            "options": {
                "temperature": options.temperature,
                "max_tokens": options.max_tokens,
                "system_prompt": options.system_prompt,
                "max_concurrency": options.max_concurrency,
            },
            "providers": [provider.public_dict() for provider in provider_list],
            "results": [result.to_dict() for result in result_list],
        }

        def sanitize(value):
            if isinstance(value, str):
                return redact_text(value, known_secrets)
            if isinstance(value, list):
                return [sanitize(item) for item in value]
            if isinstance(value, dict):
                return {key: sanitize(item) for key, item in value.items()}
            return value

        target.parent.mkdir(parents=True, exist_ok=True)
        data = json.dumps(sanitize(payload), ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        temp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=target.parent,
                prefix=f".{target.name}.",
                suffix=".tmp",
                delete=False,
            ) as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
                temp_path = Path(handle.name)
            os.replace(temp_path, target)
        finally:
            if temp_path is not None and temp_path.exists():
                temp_path.unlink(missing_ok=True)
