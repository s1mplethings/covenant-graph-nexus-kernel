from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ProviderPreset:
    name: str
    provider_id: str
    display_name: str
    base_url: str
    model: str
    secret_backend: str
    secret_ref: str


# Model names are intentionally editable. Provider catalogs change faster than
# this extension; the endpoint and credential convention are the stable preset.
PRESETS: tuple[ProviderPreset, ...] = (
    ProviderPreset(
        name="自定义 OpenAI-compatible",
        provider_id="custom",
        display_name="Custom Provider",
        base_url="https://example.invalid/v1",
        model="replace-with-model-id",
        secret_backend="session",
        secret_ref="custom",
    ),
    ProviderPreset(
        name="OpenAI",
        provider_id="openai",
        display_name="OpenAI",
        base_url="https://api.openai.com/v1",
        model="replace-with-model-id",
        secret_backend="environment",
        secret_ref="OPENAI_API_KEY",
    ),
    ProviderPreset(
        name="DeepSeek",
        provider_id="deepseek",
        display_name="DeepSeek",
        base_url="https://api.deepseek.com",
        model="deepseek-flash",
        secret_backend="environment",
        secret_ref="DEEPSEEK_API_KEY",
    ),
    ProviderPreset(
        name="Qwen / 阿里云百炼（北京共享域名）",
        provider_id="qwen",
        display_name="Qwen / Model Studio",
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        model="replace-with-model-id",
        secret_backend="environment",
        secret_ref="DASHSCOPE_API_KEY",
    ),
    ProviderPreset(
        name="SiliconFlow",
        provider_id="siliconflow",
        display_name="SiliconFlow",
        base_url="https://api.siliconflow.cn/v1",
        model="replace-with-model-id",
        secret_backend="environment",
        secret_ref="SILICONFLOW_API_KEY",
    ),
    ProviderPreset(
        name="本地 OpenAI-compatible",
        provider_id="local",
        display_name="Local Model",
        base_url="http://127.0.0.1:8000/v1",
        model="local-model",
        secret_backend="none",
        secret_ref="",
    ),
)

PRESETS_BY_NAME = {preset.name: preset for preset in PRESETS}
