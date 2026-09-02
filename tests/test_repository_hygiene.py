from __future__ import annotations

import importlib.util
import pathlib


ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "repository_hygiene.py"


def load_module():
    spec = importlib.util.spec_from_file_location("repository_hygiene_test", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write_minimum_repository(root: pathlib.Path, module) -> None:
    for relative in module.REQUIRED_SURFACES:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("fixture\n", encoding="utf-8")
    (root / ".gitignore").write_text("\n".join(module.REQUIRED_IGNORE_RULES) + "\n", encoding="utf-8")


def test_minimum_repository_passes_hygiene_check(tmp_path: pathlib.Path) -> None:
    module = load_module()
    write_minimum_repository(tmp_path, module)
    report = module.inspect_repository(tmp_path)
    assert report["ok"] is True, report["issues"]
    assert report["issues"] == []
    assert "formal delivery evidence" in report["note"]


def test_hygiene_check_reports_temp_live_support_and_missing_ignore_rule(tmp_path: pathlib.Path) -> None:
    module = load_module()
    write_minimum_repository(tmp_path, module)
    (tmp_path / ".tmp_debug").mkdir()
    live = tmp_path / "examples" / "ad_hoc" / ".cgkn"
    live.mkdir(parents=True)
    (live / "agent-kit.json").write_text("{}\n", encoding="utf-8")
    ignore = tmp_path / ".gitignore"
    ignore.write_text(ignore.read_text(encoding="utf-8").replace("/runs/\n", ""), encoding="utf-8")

    report = module.inspect_repository(tmp_path)
    codes = {item["code"] for item in report["issues"]}

    assert report["ok"] is False
    assert "ROOT_TEMP_PRESENT" in codes
    assert "LIVE_SUPPORT_STATE_IN_EXAMPLES" in codes
    assert "IGNORE_BOUNDARY_MISSING" in codes
