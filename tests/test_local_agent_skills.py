from __future__ import annotations

import json
import pathlib
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import scripts.local_agent_actions as local_actions
import scripts.local_agent_skills as skills


class LocalAgentSkillsTests(unittest.TestCase):
    def test_search_skills_finds_patch_file(self) -> None:
        result = skills.search_skills("small patch file edit")

        self.assertTrue(result["ok"])
        self.assertTrue(any(item["name"] == "patch_file" for item in result["skills"]))

    def test_patch_file_modifies_project_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = pathlib.Path(temp_dir)
            readme = project / "README.md"
            readme.write_text("hello old text\n", encoding="utf-8")

            result = skills.use_skill(project, "patch_file", {"path": "README.md", "find": "old text", "replace": "new text"})

            self.assertTrue(result["ok"])
            self.assertEqual(1, result["replacements"])
            self.assertIn("new text", readme.read_text(encoding="utf-8"))

    def test_patch_file_cannot_escape_project_dir(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = pathlib.Path(temp_dir) / "project"
            project.mkdir()
            outside = pathlib.Path(temp_dir) / "outside.txt"
            outside.write_text("old", encoding="utf-8")

            result = skills.use_skill(project, "patch_file", {"path": "../outside.txt", "find": "old", "replace": "new"})

            self.assertFalse(result["ok"])
            self.assertEqual("old", outside.read_text(encoding="utf-8"))

    def test_delete_file_removes_only_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = pathlib.Path(temp_dir)
            target = project / "unused.txt"
            target.write_text("unused", encoding="utf-8")

            result = skills.use_skill(project, "delete_file", {"path": "unused.txt"})

            self.assertTrue(result["ok"])
            self.assertTrue(result["deleted"])
            self.assertFalse(target.exists())

    def test_delete_file_rejects_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = pathlib.Path(temp_dir)
            (project / "assets").mkdir()

            result = skills.use_skill(project, "delete_file", {"path": "assets"})

            self.assertFalse(result["ok"])
            self.assertTrue((project / "assets").is_dir())

    def test_write_json_writes_pretty_json(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = pathlib.Path(temp_dir)

            result = skills.use_skill(project, "write_json", {"path": "config/app.json", "value": {"name": "demo"}})

            self.assertTrue(result["ok"])
            text = (project / "config" / "app.json").read_text(encoding="utf-8")
            self.assertIn('\n  "name": "demo"\n', text)
            self.assertEqual({"name": "demo"}, json.loads(text))

    def test_run_tests_returns_failed_result_without_exception(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = pathlib.Path(temp_dir)

            result = skills.use_skill(project, "run_tests", {"command": "python missing_file.py", "timeout": 30})

            self.assertFalse(result["ok"])
            self.assertNotEqual(0, result["returncode"])
            self.assertIn("stderr_tail", result)

    def test_run_tests_python_command_uses_argv_split(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = pathlib.Path(temp_dir)

            result = skills.use_skill(project, "run_tests", {"command": "python missing_file.py", "timeout": 30})

            self.assertEqual(["python", "missing_file.py"], result["argv"])
            self.assertNotEqual("python missing_file.py", result["argv"][0])

    def test_run_tests_rejects_shell_chaining(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = pathlib.Path(temp_dir)

            result = skills.use_skill(project, "run_tests", {"command": "python ok.py; del important.txt", "timeout": 30})

            self.assertFalse(result["ok"])
            self.assertIn("shell chaining", result["error"])

    def test_http_request_rejects_public_url(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            result = skills.use_skill(pathlib.Path(temp_dir), "http_request", {"method": "GET", "url": "https://example.com"})

            self.assertFalse(result["ok"])
            self.assertIn("localhost", result["error"])

    def test_browser_screenshot_missing_playwright_returns_tool_error(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = pathlib.Path(temp_dir)

            result = skills.use_skill(project, "browser_screenshot", {"url": "http://127.0.0.1:9", "output_path": "artifacts/home.png"})

            self.assertFalse(result["ok"])
            self.assertEqual("browser_screenshot", result["skill"])
            self.assertIn("Playwright", result["actionable"])

    def test_propose_skill_writes_draft_only(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = pathlib.Path(temp_dir)

            result = skills.propose_skill(project, "sqlite_query", "Query a local SQLite database", {"inputs": ["sql"]}, "Needs review.")

            self.assertTrue(result["ok"])
            draft_path = pathlib.Path(result["draft_path"])
            self.assertTrue(draft_path.exists())
            draft = json.loads(draft_path.read_text(encoding="utf-8"))
            self.assertFalse(draft["approved"])
            self.assertFalse(draft["dynamic_execution_enabled"])
            self.assertTrue((draft_path.parent / "notes.md").exists())

    def test_proposed_skill_is_not_available_to_use_skill(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = pathlib.Path(temp_dir)
            skills.propose_skill(project, "sqlite_query", "Query SQLite", {}, "")

            result = skills.use_skill(project, "sqlite_query", {"sql": "select 1"})

            self.assertFalse(result["ok"])
            self.assertIn("not approved", result["error"])

    def test_local_agent_actions_can_search_and_use_skill(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = pathlib.Path(temp_dir)
            (project / "README.md").write_text("hello old\n", encoding="utf-8")
            executor = local_actions.LocalAgentActionExecutor(project)

            search = executor.execute({"type": "search_skills", "query": "patch file"})
            patch = executor.execute({"type": "use_skill", "name": "patch_file", "args": {"path": "README.md", "find": "old", "replace": "new"}})

            self.assertTrue(search["ok"])
            self.assertTrue(any(item["name"] == "patch_file" for item in search["skills"]))
            self.assertTrue(patch["ok"])
            self.assertIn("new", (project / "README.md").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
