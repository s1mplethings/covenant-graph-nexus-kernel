from __future__ import annotations

import inspect
import pathlib
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import local_usage_planner


class LocalUsagePlannerTests(unittest.TestCase):
    def test_index_html_routes_static_html(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project_dir = pathlib.Path(temp_dir)
            (project_dir / "index.html").write_text("<html></html>", encoding="utf-8")
            plan = local_usage_planner.create_usage_plan(project_dir)
            self.assertEqual("static_html", plan["run_mode"])

    def test_static_html_inventory_follows_declared_src_assets(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project_dir = pathlib.Path(temp_dir)
            (project_dir / "src").mkdir()
            (project_dir / "index.html").write_text(
                '<link rel="stylesheet" href="src/styles.css">'
                '<script type="module" src="./src/app.js"></script>',
                encoding="utf-8",
            )
            (project_dir / "src" / "styles.css").write_text("body{}", encoding="utf-8")
            (project_dir / "src" / "app.js").write_text("export {};", encoding="utf-8")
            (project_dir / "README.md").write_text("# Demo", encoding="utf-8")

            plan = local_usage_planner.create_usage_plan(project_dir)

            self.assertEqual(
                ["index.html", "src/styles.css", "src/app.js", "README.md"],
                [item["path"] for item in plan["required_files"]],
            )
            self.assertTrue(all(item["exists"] for item in plan["required_files"]))

    def test_package_json_routes_node_project(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project_dir = pathlib.Path(temp_dir)
            (project_dir / "package.json").write_text("{}", encoding="utf-8")
            plan = local_usage_planner.create_usage_plan(project_dir)
            self.assertEqual("node_project", plan["run_mode"])

    def test_requirements_routes_python_project(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project_dir = pathlib.Path(temp_dir)
            (project_dir / "requirements.txt").write_text("pytest\n", encoding="utf-8")
            plan = local_usage_planner.create_usage_plan(project_dir)
            self.assertEqual("python_project", plan["run_mode"])

    def test_unknown_project_returns_partial(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            plan = local_usage_planner.create_usage_plan(pathlib.Path(temp_dir))
            self.assertEqual("unknown", plan["run_mode"])
            self.assertEqual("PARTIAL", plan["status"])

    def test_planner_does_not_call_network_or_provider(self) -> None:
        source = inspect.getsource(local_usage_planner).lower()
        self.assertNotIn("openai", source)
        self.assertNotIn("requests.post", source)
        self.assertNotIn("httpx.post", source)
        self.assertNotIn("urllib.request.urlopen", source)


if __name__ == "__main__":
    unittest.main()
