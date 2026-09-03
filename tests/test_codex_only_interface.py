from __future__ import annotations

import ast
import pathlib
import subprocess


ROOT = pathlib.Path(__file__).resolve().parents[1]
TEXT_SUFFIXES = {
    ".json",
    ".jsonl",
    ".md",
    ".py",
    ".ps1",
    ".toml",
    ".txt",
    ".yaml",
    ".yml",
}


def repository_text_files() -> list[pathlib.Path]:
    proc = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        cwd=ROOT,
        capture_output=True,
        check=True,
    )
    return [
        ROOT / pathlib.Path(raw.decode("utf-8"))
        for raw in proc.stdout.split(b"\0")
        if raw and pathlib.Path(raw.decode("utf-8")).suffix.lower() in TEXT_SUFFIXES
    ]


def test_repository_has_only_codex_conversation_interface() -> None:
    retired_terms = (
        "tele" + "gram",
        "mini" + " app",
        "web" + "_app",
        "bot" + " token",
        "bot" + " api",
    )
    findings: list[str] = []
    for path in repository_text_files():
        if not path.is_file():
            continue
        lowered = path.read_text(encoding="utf-8", errors="replace").lower()
        for term in retired_terms:
            if term in lowered:
                findings.append(f"{path.relative_to(ROOT)}: {term}")
    assert findings == []


def test_retired_conversation_services_and_launchers_are_absent() -> None:
    retired_paths = (
        ROOT / "scripts" / ("tele" + "gram_live_bridge.py"),
        ROOT / "scripts" / ("tele" + "gram_new_listener.py"),
        ROOT / "scripts" / ("start_tele" + "gram_new_listener.ps1"),
        ROOT / "scripts" / ("start_cgkn_" + "codex_edition.ps1"),
        ROOT / "scripts" / "start_cgkn_api_only.ps1",
        ROOT / ("start_customer_" + "service.py"),
    )
    assert [str(path.relative_to(ROOT)) for path in retired_paths if path.exists()] == []


def test_codex_conversation_module_is_import_only() -> None:
    path = ROOT / "scripts" / "codex_conversation.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    top_level_main = [
        node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "main"
    ]
    assert top_level_main == []
    assert not any(isinstance(node, ast.If) and "__main__" in ast.unparse(node.test) for node in tree.body)


def test_codex_only_contract_preserves_governed_delivery_route() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    kernel = (ROOT / "docs" / "00_kernel_contract.md").read_text(encoding="utf-8")
    assert "operated only through the Codex conversation" in readme
    for marker in (
        "provider output validation",
        "post-build finalization",
        "local_packager",
        "public_delivery_gate",
        "delivery_manifest.json",
        "whiteboard",
        "agent_session",
    ):
        assert marker.lower() in kernel.lower() or marker.lower() in readme.lower()
