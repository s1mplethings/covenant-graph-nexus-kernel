from __future__ import annotations

import pathlib
import re


ROOT = pathlib.Path(__file__).resolve().parents[1]
MARK_PATTERN = re.compile(r"pytest\.mark\.([A-Za-z_][A-Za-z0-9_]*)")


def _markers(text: str) -> set[str]:
    return set(MARK_PATTERN.findall(text))


def _required_markers(path: pathlib.Path, text: str) -> list[tuple[set[str], str]]:
    stem = path.stem.lower()
    lowered = text.lower()
    requirements: list[tuple[set[str], str]] = []
    if stem == "test_quick_large_sync_tree_benchmark":
        requirements.append(({"quick"}, "quick mock benchmark should run in targeted/quick tests"))
        return requirements
    if any(token in stem for token in ("benchmark", "long_run", "full_pytest", "timeout_diagnosis")):
        requirements.append(({"slow", "benchmark"}, "long-running/benchmark naming"))
    if ("codex" in stem and "contract" not in stem) or any(token.lower() in lowered for token in ("sendphoto", "senddocument")):
        requirements.append(({"codex"}, "Codex conversation runtime naming/content"))
    provider_name = any(token in stem for token in ("live_provider", "provider_api"))
    provider_network = any(token in lowered for token in ("gptsapi", "openai_api_key", "cgkn_openai_api_key")) and any(
        token in lowered for token in ("urlopen(", "invoke-restmethod", "curl ")
    )
    if provider_name and "transport" not in stem or provider_network:
        requirements.append(({"live_provider"}, "live provider naming/network content"))
    if any(token in stem for token in ("e2e", "end_to_end", "real_project")):
        requirements.append(({"e2e", "integration"}, "end-to-end/integration naming"))
    return requirements


def test_profile_sensitive_tests_declare_markers() -> None:
    violations = []
    paths = sorted((ROOT / "tests").glob("test_*.py")) + sorted((ROOT / "scripts").glob("test_*.py"))
    for path in paths:
        if path.name == pathlib.Path(__file__).name:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        markers = _markers(text)
        for allowed, reason in _required_markers(path, text):
            if markers.isdisjoint(allowed):
                violations.append(f"{path.relative_to(ROOT)}: requires one of {sorted(allowed)} ({reason})")
    assert not violations, "Missing pytest profile markers:\n" + "\n".join(violations)
