from __future__ import annotations

import pathlib
import os
import subprocess
import sys
import tempfile
import unittest

import pytest

pytestmark = pytest.mark.slow

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import scripts.canonical_evidence_hash as canonical_evidence_hash
import scripts.canonical_media_validation as canonical_media_validation
import scripts.telegram_live_bridge as bridge


class ProviderPostBuildFinalizeTests(unittest.TestCase):
    def test_canonical_playwright_visual_satisfies_screenshot_without_provider_ui_image(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            project = root / "project"
            project.mkdir()
            (project / "index.html").write_text(
                "<main><h1>Canonical browser capture</h1><button>Run</button></main>\n",
                encoding="utf-8",
            )
            (project / "README.md").write_text("# Browser capture\n", encoding="utf-8")
            (project / "tests").mkdir()
            (project / "tests" / "test_app.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")
            session_dir = root / "sessions"
            session = bridge.default_session("chat-canonical-browser-only")
            session["messages"].append(
                {
                    "role": "user",
                    "text": "做一个网页并交付真实界面截图",
                    "created_at": bridge.now(),
                }
            )
            session["whiteboard"]["delivery_requirements"] = ["界面截图"]

            result = bridge.post_build_finalize_provider_project(
                project,
                {"status": "PASS", "example_outputs": {}, "agent_usage": {"events": []}},
                {"copied": {}},
                session,
                session_dir=session_dir,
                chat_id="chat-canonical-browser-only",
            )

            self.assertFalse(result["image_result"].get("ui_screenshot"))
            self.assertEqual([], result["image_result"]["missing"])
            self.assertEqual("PASS", result["visual_evidence_result"]["status"], result["visual_evidence_result"])
            self.assertEqual("PASS", result["manifest"]["status"], result["manifest"])
            self.assertTrue(result["manifest"]["visual_evidence_ref"])
            self.assertEqual(
                canonical_evidence_hash.sha256_file(result["manifest"]["visual_evidence_ref"]),
                result["manifest"]["visual_evidence_hash"],
            )
            self.assertEqual("PASS", result["gate"]["canonical_package_inspection"]["status"], result["gate"])

    def test_entrypoint_and_dependency_repairs_are_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = pathlib.Path(temp_dir) / "project"
            (project / "src").mkdir(parents=True)
            (project / "src" / "main.py").write_text(
                "from src.config import settings\n\n"
                "def main():\n"
                "    print(settings.app_name)\n",
                encoding="utf-8",
            )
            (project / "src" / "config.py").write_text(
                "from pydantic import BaseSettings, Field\n\n"
                "class Settings(BaseSettings):\n"
                "    app_name: str = Field(default='VN')\n"
                "settings = Settings()\n",
                encoding="utf-8",
            )
            (project / "src" / "main.py").write_text(
                "from fastapi import FastAPI\n\napp = FastAPI()\n",
                encoding="utf-8",
            )
            (project / "src" / "image_use.py").write_text("from PIL import Image\n", encoding="utf-8")
            (project / "tests").mkdir()
            (project / "tests" / "test_ui.py").write_text(
                "from flask import Flask\nfrom src.main import create_app\n",
                encoding="utf-8",
            )
            (project / "requirements.txt").write_text("pydantic==1.10.7\nfastapi==0.95.2\n", encoding="utf-8")

            launcher = bridge.ensure_provider_root_launcher(project)
            repair = bridge.deterministic_post_build_repair(
                project,
                {"stdout": "No module named PIL._deprecate\nBaseSettings has been moved", "stderr": "", "exit_code": 2},
            )

            self.assertTrue(launcher["changed"])
            self.assertTrue((project / "main.py").exists())
            config_text = (project / "src" / "config.py").read_text(encoding="utf-8")
            self.assertIn("from pydantic_settings import BaseSettings", config_text)
            requirements = (project / "requirements.txt").read_text(encoding="utf-8").lower()
            self.assertIn("pydantic-settings", requirements)
            self.assertIn("pillow>=10,<12", requirements)
            self.assertIn("fastapi>=0.115,<1", requirements)
            self.assertIn("flask>=3,<4", requirements)
            self.assertIn("def create_app", (project / "src" / "main.py").read_text(encoding="utf-8"))
            self.assertEqual("dependency_environment_error", repair["failure_type"])

    def test_provider_interface_repair_fixes_generated_test_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = pathlib.Path(temp_dir) / "project"
            (project / "src" / "backend").mkdir(parents=True)
            (project / "src" / "__init__.py").write_text("", encoding="utf-8")
            (project / "src" / "main.py").write_text(
                "from fastapi import FastAPI\n\napp = FastAPI()\n",
                encoding="utf-8",
            )
            (project / "src" / "backend" / "__init__.py").write_text("", encoding="utf-8")
            (project / "src" / "backend" / "image_generator.py").write_text(
                "\n".join(
                    [
                        "import os, uuid",
                        "from PIL import Image",
                        "IMAGE_OUTPUT_DIR = 'media/generated_images'",
                        "class ImageGenerator:",
                        "    def generate_background(self, prompt, width=800, height=600):",
                        "        os.makedirs(IMAGE_OUTPUT_DIR, exist_ok=True)",
                        "        path = os.path.join(IMAGE_OUTPUT_DIR, f'background_{uuid.uuid4().hex}.png')",
                        "        Image.new('RGB', (width, height), (20, 80, 120)).save(path)",
                        "        return path",
                        "    def generate_character_sprite(self, prompt, width=400, height=600):",
                        "        os.makedirs(IMAGE_OUTPUT_DIR, exist_ok=True)",
                        "        path = os.path.join(IMAGE_OUTPUT_DIR, f'sprite_{uuid.uuid4().hex}.png')",
                        "        Image.new('RGB', (width, height), (120, 80, 20)).save(path)",
                        "        return path",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            (project / "src" / "backend" / "image_generation.py").write_text(
                "\n".join(
                    [
                        "from PIL import Image",
                        "class ImageGeneratorInterface:",
                        "    def generate_background(self, prompt, width=800, height=600):",
                        "        raise NotImplementedError",
                        "class DummyImageGenerator(ImageGeneratorInterface):",
                        "    def generate_background(self, prompt, width=800, height=600):",
                        "        return Image.new('RGB', (width, height), (20, 80, 120))",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            (project / "src" / "backend" / "timeline_manager.py").write_text(
                "\n".join(
                    [
                        "import json",
                        "class StoryNode:",
                        "    def __init__(self, node_id='', title='', content=''):",
                        "        self.node_id = node_id",
                        "        self.title = title",
                        "        self.content = content",
                        "        self.next_nodes = []",
                        "class TimelineManager:",
                        "    def __init__(self):",
                        "        self.nodes = {}",
                        "        self.start_node_id = None",
                        "    def add_node(self, title, content):",
                        "        node = StoryNode(title=title, content=content)",
                        "        self.nodes[id(node)] = node",
                        "        return id(node)",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            (project / "src" / "backend" / "timeline.py").write_text(
                "\n".join(
                    [
                        "class StoryTimeline:",
                        "    def __init__(self):",
                        "        self.nodes = {}",
                        "        self.start_node_id = None",
                        "    def add_node(self, title, content):",
                        "        node_id = str(len(self.nodes) + 1)",
                        "        self.nodes[node_id] = {'title': title, 'content': content, 'next_nodes': []}",
                        "        return node_id",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            (project / "src" / "project_structure.py").write_text(
                "from pathlib import Path\nPROJECT_ROOT = Path(__file__).parent.parent.resolve()\n",
                encoding="utf-8",
            )
            (project / "src" / "backend" / "cli.py").write_text(
                "\n".join(
                    [
                        "import argparse",
                        "import sys",
                        "from backend.timeline_manager import TimelineManager",
                        "def main():",
                        "    parser = argparse.ArgumentParser(description=\"VN Project Assistant CLI\")",
                        "    parser.add_argument('--export', metavar='PROJECT_NAME')",
                        "    args = parser.parse_args()",
                        "    if args.export:",
                        "        print('exported')",
                        "if __name__ == '__main__':",
                        "    main()",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            (project / "src" / "backend" / "app.py").write_text(
                "from backend.timeline_manager import TimelineManager\n\napp = object()\n",
                encoding="utf-8",
            )
            (project / "src" / "backend" / "project_data.py").write_text(
                "class ProjectDataStore:\n    pass\n",
                encoding="utf-8",
            )
            (project / "src" / "backend" / "project_api.py").write_text(
                "from backend.timeline_manager import TimelineManager\n\napi = object()\n",
                encoding="utf-8",
            )
            (project / "requirements.txt").write_text("pytest\npillow>=10,<12\n", encoding="utf-8")
            (project / "tests").mkdir()
            (project / "tests" / "test_generated_interfaces.py").write_text(
                "\n".join(
                    [
                        "import os, subprocess, sys",
                        "from src.backend.image_generator import ImageGenerator",
                        "from src.backend.image_generation import BackgroundGenerator, CharacterSpriteGenerator",
                        "from src.backend.timeline_manager import TimelineManager",
                        "from src.backend.timeline import StoryTimeline, StoryNode",
                        "from src.project_structure import StoryTimeline as ProjectStoryTimeline",
                        "from src.backend.cli import VNProjectCLI",
                        "from src.backend.project_data import ProjectData",
                        "from src.backend.project_api import ProjectAPI",
                        "from src.backend import main as backend_main",
                        "from src.frontend import main as frontend_main",
                        "",
                        "def test_image_generator_compat(tmp_path):",
                        "    gen = ImageGenerator()",
                        "    assert os.path.isfile(gen.generate_background('forest', output_dir=str(tmp_path)))",
                        "    assert os.path.isfile(gen.generate_sprite('hero', output_dir=str(tmp_path)))",
                        "    assert os.path.isfile(gen.generate_background('forest', str(tmp_path)))",
                        "    assert os.path.isfile(gen.generate_sprite('hero', str(tmp_path)))",
                        "    assert os.path.exists(gen.generate_background('forest').file_path)",
                        "    assert os.path.exists(gen.generate_sprite('hero').file_path)",
                        "    assert os.path.isfile(BackgroundGenerator().generate('forest', output_dir=str(tmp_path)))",
                        "    assert os.path.isfile(CharacterSpriteGenerator().generate('hero', output_dir=str(tmp_path)))",
                        "",
                        "def test_timeline_compat(tmp_path):",
                        "    timeline = TimelineManager()",
                        "    timeline.add_node('start', {'text': 'Start'})",
                        "    timeline.add_edge('start', 'middle')",
                        "    assert ('start', 'middle') in timeline.get_edges()",
                        "    title_id = timeline.add_node('Start', description='Start of story')",
                        "    assert timeline.get_node(title_id)['title'] == 'Start'",
                        "    assert 'Start' in timeline.serialize()",
                        "    story = StoryTimeline()",
                        "    start_id = story.add_node('Start', description='The beginning')",
                        "    branch_id = story.add_node('Branch')",
                        "    story.add_branch(start_id, branch_id)",
                        "    assert branch_id in story.nodes[start_id]['branches']",
                        "    assert story.get_node(start_id)['title'] == 'Start'",
                        "    assert branch_id in story.get_branches(start_id)",
                        "    story.remove_node(branch_id)",
                        "    assert branch_id not in story.nodes",
                        "    timeline_json = tmp_path / 'story.json'",
                        "    story.save_to_file(timeline_json)",
                        "    loaded_story = StoryTimeline.load_from_file(timeline_json)",
                        "    assert loaded_story.get_node(start_id)['title'] == 'Start'",
                        "    assert 'Start' in [node['title'] for node in story.to_dict()['nodes']]",
                        "    project_story = ProjectStoryTimeline()",
                        "    project_story.add_event('start', description='Start')",
                        "    project_story.add_event('conflict', description='Conflict')",
                        "    project_story.add_event('resolution', description='Resolution')",
                        "    project_story.add_dependency('start', 'conflict')",
                        "    project_story.add_dependency('conflict', 'resolution')",
                        "    assert project_story.get_ordered_events() == ['start', 'conflict', 'resolution']",
                        "    project_story.add_dependency('resolution', 'start')",
                        "    assert project_story.has_cycle()",
                        "    node1 = StoryNode(id='node1', content='Start')",
                        "    node2 = StoryNode(id='node2', content='Middle', parent_id='node1')",
                        "    object_story = StoryTimeline()",
                        "    object_story.add_node(node1)",
                        "    object_story.add_node(node2)",
                        "    assert [node.id for node in object_story.get_ordered_nodes()] == ['node1', 'node2']",
                        "    assert [node.id for node in object_story.get_children('node1')] == ['node2']",
                        "",
                        "def test_cli_compat(tmp_path):",
                        "    assert subprocess.run([sys.executable, 'src/backend/cli.py', '--help']).returncode == 0",
                        "    result = subprocess.run([sys.executable, 'src/backend/cli.py', 'export', '--format', 'json'], capture_output=True, text=True)",
                        "    assert result.returncode == 0",
                        "    assert 'exported' in result.stdout.lower()",
                        "    added = subprocess.run([sys.executable, 'src/backend/cli.py', 'add-node', 'TestNode', 'Description'], capture_output=True, text=True)",
                        "    assert added.returncode == 0",
                        "    assert 'Node added' in added.stdout",
                        "    version = subprocess.run([sys.executable, 'src/backend/app.py', '--version'], capture_output=True, text=True)",
                        "    assert version.returncode == 0",
                        "    assert 'Version' in version.stdout",
                        "    image = subprocess.run([sys.executable, 'src/backend/image_generator.py', '--test'], capture_output=True, text=True)",
                        "    assert image.returncode == 0",
                        "    assert 'Image generation test passed' in image.stdout",
                        "    help_result = subprocess.run([sys.executable, 'src/main.py', '--help'], capture_output=True, text=True)",
                        "    assert help_result.returncode == 0",
                        "    assert 'usage' in help_result.stdout.lower()",
                        "    cli_image = subprocess.run([sys.executable, 'src/main.py', '--generate-background', 'beach', '--output', str(tmp_path / 'output_test.png')], capture_output=True, text=True)",
                        "    assert cli_image.returncode == 0",
                        "    assert os.path.exists(tmp_path / 'output_test.png')",
                        "    cli = VNProjectCLI()",
                        "    background = cli.export_background('lake', output_dir=str(tmp_path))",
                        "    assert os.path.isfile(background)",
                        "    node_id = cli.timeline.add_node('Start')",
                        "    assert node_id in cli.timeline.nodes",
                        "    api = ProjectAPI()",
                        "    project_id = api.create_project('Test VN Project')",
                        "    assert isinstance(api.get_timeline(project_id), dict)",
                        "    assert api.export_project(project_id).endswith('.json')",
                        "    assert api.generate_background(project_id, 'forest')",
                        "    assert api.generate_sprite(project_id, 'hero')",
                        "",
                        "def test_backend_frontend_compat():",
                        "    assert backend_main.main(start_server=False)",
                        "    assert frontend_main.main(run_ui=False)",
                        "",
                        "def test_project_data_export(tmp_path):",
                        "    project = ProjectData()",
                        "    project.timeline.add_node('Start')",
                        "    timeline_path = tmp_path / 'timeline.json'",
                        "    project.export_timeline_json(timeline_path)",
                        "    assert 'nodes' in timeline_path.read_text()",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            first = bridge.run_provider_project_tests(project)
            self.assertFalse(first["ok"])
            repair = bridge.deterministic_post_build_repair(project, first)
            (project / "PIL").mkdir()
            (project / "PIL" / "__init__.py").write_text("from . import Image, ImageDraw\n", encoding="utf-8")
            (project / "PIL" / "Image.py").write_text(
                "\n".join(
                    [
                        "class _Image:",
                        "    def __init__(self, size=(1, 1), color=(0, 0, 0)):",
                        "        self.size = size",
                        "        self.color = color",
                        "    def save(self, path):",
                        "        with open(path, 'wb') as handle:",
                        "            handle.write(b'fake-png')",
                        "def new(mode, size, color):",
                        "    return _Image(size=size, color=color)",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            (project / "PIL" / "ImageDraw.py").write_text(
                "\n".join(
                    [
                        "class _Draw:",
                        "    def __init__(self, image):",
                        "        self.image = image",
                        "    def text(self, *args, **kwargs):",
                        "        return None",
                        "    def line(self, *args, **kwargs):",
                        "        return None",
                        "    def ellipse(self, *args, **kwargs):",
                        "        return None",
                        "    def rectangle(self, *args, **kwargs):",
                        "        return None",
                        "def Draw(image):",
                        "    return _Draw(image)",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            dependency_setup = {
                "ok": True,
                "python": sys.executable,
                "venv_dir": "",
                "steps": [{"ok": True, "command": "reuse current test interpreter for deterministic no-live repair test"}],
            }
            second = bridge.run_provider_project_tests(
                project,
                python_executable=dependency_setup.get("python"),
                repair_summary=repair,
                dependency_setup=dependency_setup,
            )

            self.assertTrue(repair["provider_interfaces"]["changed"])
            self.assertTrue((project / "src" / "backend" / "main.py").exists())
            self.assertTrue((project / "src" / "frontend" / "main.py").exists())
            self.assertTrue(dependency_setup["ok"], dependency_setup)
            self.assertTrue(second["ok"], second)
            self.assertIn("configfile: pytest.ini", second["stdout"])
            customer_env = os.environ.copy()
            customer_env.pop("CGKN_TEST_OUTPUT_DIR", None)
            customer_env["PYTHONPATH"] = os.pathsep.join([str(project), str(project / "src"), customer_env.get("PYTHONPATH", "")])
            customer_proc = subprocess.run(
                [
                    sys.executable,
                    "-c",
                    "\n".join(
                        [
                            "from pathlib import Path",
                            "from src.backend.image_generator import ImageGenerator",
                            "from src.backend.project_api import ProjectAPI",
                            "gen = ImageGenerator()",
                            "bg = Path(gen.generate_background('customer-default'))",
                            "sp = Path(gen.generate_sprite('customer-default'))",
                            "api = ProjectAPI()",
                            "pid = api.create_project('Customer')",
                            "exported = Path(api.export_project(pid))",
                            "api_bg = Path(api.generate_background(pid, 'lake'))",
                            "assert bg.exists() and sp.exists() and exported.exists() and api_bg.exists()",
                            "assert bg.parts[:2] == ('media', 'generated_images')",
                            "assert sp.parts[:2] == ('media', 'generated_images')",
                            "assert exported.parts[0] == 'export'",
                            "assert api_bg.parts[:2] == ('media', 'generated_images')",
                        ]
                    ),
                ],
                cwd=project,
                env=customer_env,
                capture_output=True,
                text=True,
                timeout=30,
            )
            self.assertEqual(0, customer_proc.returncode, customer_proc.stderr or customer_proc.stdout)

    def test_provider_runtime_repair_adds_fastapi_script_entrypoint(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = pathlib.Path(temp_dir) / "project"
            (project / "src" / "backend").mkdir(parents=True)
            (project / "src" / "__init__.py").write_text("", encoding="utf-8")
            (project / "src" / "backend" / "__init__.py").write_text("", encoding="utf-8")
            (project / "src" / "backend" / "app.py").write_text(
                "from fastapi import FastAPI\n\napp = FastAPI()\n",
                encoding="utf-8",
            )
            (project / "requirements.txt").write_text("fastapi==0.95.2\npytest==7.3.1\n", encoding="utf-8")
            (project / "tests").mkdir()
            (project / "tests" / "test_local_runtime.py").write_text(
                "\n".join(
                    [
                        "import subprocess",
                        "",
                        "def test_startup():",
                        "    proc = subprocess.Popen(['python', 'src/backend/app.py'])",
                        "    proc.terminate()",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            repair = bridge.deterministic_post_build_repair(
                project,
                {"ok": False, "stdout": "AssertionError: 0 is not None", "stderr": "", "failure_type": "pytest_failed"},
            )

            app_source = (project / "src" / "backend" / "app.py").read_text(encoding="utf-8")
            requirements = (project / "requirements.txt").read_text(encoding="utf-8").lower()
            self.assertTrue(repair["provider_interfaces"]["changed"])
            self.assertIn("uvicorn.run", app_source)
            self.assertIn("uvicorn>=0.22,<1", requirements)

    def test_provider_artifact_repair_materializes_export_and_image_fixtures(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = pathlib.Path(temp_dir) / "project"
            (project / "tests").mkdir(parents=True)
            (project / "tests" / "test_artifacts.py").write_text(
                "\n".join(
                    [
                        "from pathlib import Path",
                        "BACKGROUND_DIR = Path('./assets/backgrounds')",
                        "CHARACTER_DIR = Path('./assets/characters')",
                        "STORY_TIMELINE_PATH = Path('./data/story_timeline.json')",
                        "EXPORT_PATHS = [Path('./export/project.json'), Path('./export/backgrounds/background_list.json'), Path('./export/characters/character_list.json'), Path('./export/story_timeline.json')]",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            result = bridge.materialize_provider_test_artifacts(project)

            self.assertTrue(result["changed"])
            self.assertTrue((project / "data" / "story_timeline.json").exists())
            self.assertTrue((project / "assets" / "backgrounds" / "background_demo.png").exists())
            self.assertTrue((project / "assets" / "characters" / "sprite_demo.png").exists())
            self.assertTrue((project / "export" / "project.json").exists())
            self.assertTrue((project / "export" / "backgrounds" / "background_list.json").exists())
            self.assertTrue((project / "export" / "characters" / "character_list.json").exists())
            self.assertTrue((project / "export" / "story_timeline.json").exists())

    def test_provider_pytest_env_supports_src_and_top_level_backend_imports(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = pathlib.Path(temp_dir) / "project"
            (project / "src" / "backend").mkdir(parents=True)
            (project / "src" / "__init__.py").write_text("", encoding="utf-8")
            (project / "src" / "backend" / "__init__.py").write_text("", encoding="utf-8")
            (project / "src" / "backend" / "timeline_manager.py").write_text(
                "class TimelineManager:\n    pass\n",
                encoding="utf-8",
            )
            (project / "src" / "backend" / "project_api.py").write_text(
                "from backend.timeline_manager import TimelineManager\n\nclass ProjectAPI:\n    manager = TimelineManager\n",
                encoding="utf-8",
            )
            (project / "tests").mkdir()
            (project / "tests" / "test_imports.py").write_text(
                "from src.backend.project_api import ProjectAPI\n\ndef test_imports():\n    assert ProjectAPI.manager\n",
                encoding="utf-8",
            )

            result = bridge.run_provider_project_tests(project)

            self.assertTrue(result["ok"], result)

    def test_post_build_finalize_runs_tests_images_package_and_gate(self) -> None:
        try:
            import PIL  # noqa: F401
        except Exception:
            self.skipTest("Pillow is required for image evidence fixture")

        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            project = root / "project"
            project.mkdir()
            (project / "README.md").write_text("# VN Assistant\n\nRun `python app.py`.\n", encoding="utf-8")
            (project / "app.py").write_text("print('vn assistant')\n", encoding="utf-8")
            (project / "index.html").write_text("<main><h1>VN Assistant</h1><button>Export</button></main>\n", encoding="utf-8")
            (project / "requirements.txt").write_text("pytest\nPillow\n", encoding="utf-8")
            (project / "tests").mkdir()
            (project / "tests" / "test_app.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")
            (project / "models").mkdir()
            (project / "models" / "__init__.py").write_text("", encoding="utf-8")
            (project / "models" / "image_generator.py").write_text(
                "\n".join(
                    [
                        "import pathlib",
                        "from PIL import Image, ImageDraw",
                        "",
                        "class LocalImageGenerator:",
                        "    def __init__(self, assets_dir='assets/generated'):",
                        "        self.assets_dir = pathlib.Path(assets_dir)",
                        "        self.assets_dir.mkdir(parents=True, exist_ok=True)",
                        "    def generate_background(self, scene_name):",
                        "        path = self.assets_dir / f'background_{scene_name}.png'",
                        "        img = Image.new('RGB', (640, 360), (20, 30, 80))",
                        "        draw = ImageDraw.Draw(img)",
                        "        for x in range(0, 640, 20):",
                        "            draw.line((x, 0, 640-x, 360), fill=(40 + x % 180, 120, 200))",
                        "        draw.text((40, 150), 'generated background', fill=(255, 255, 255))",
                        "        img.save(path)",
                        "        return str(path)",
                        "    def generate_character_sprite(self, character_name):",
                        "        path = self.assets_dir / f'sprite_{character_name}.png'",
                        "        img = Image.new('RGBA', (320, 480), (0, 0, 0, 0))",
                        "        draw = ImageDraw.Draw(img)",
                        "        draw.ellipse((90, 30, 230, 170), fill=(250, 220, 180, 255))",
                        "        draw.rectangle((120, 170, 200, 420), fill=(120, 70, 180, 255))",
                        "        draw.text((50, 430), 'generated sprite', fill=(255, 255, 255, 255))",
                        "        img.save(path)",
                        "        return str(path)",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            session_dir = root / "sessions"
            session = bridge.default_session("chat-vn-post")
            session["messages"].append(
                {
                    "role": "user",
                    "text": "帮我做一个本地可运行的 VN 项目助手，可以生成背景，立绘，本地模型，桌面界面，文件导出",
                    "created_at": bridge.now(),
                }
            )
            session["whiteboard"]["local_image_model_discovery"] = {"checked": True, "available": True}
            screenshot = project / "runtime_ui_screenshot.png"
            background = project / "runtime_generated_background.png"
            sprite = project / "runtime_generated_sprite.png"
            bridge.write_rgb_png(
                screenshot,
                640,
                360,
                lambda x, y: ((x * 3 + y) % 255, (x + y * 2) % 255, (x * 2 + y * 3) % 255),
            )
            bridge.write_rgb_png(
                background,
                640,
                360,
                lambda x, y: ((x * 5 + y) % 255, (x + y * 3) % 255, (x * 2 + y) % 255),
            )
            bridge.write_rgb_png(
                sprite,
                320,
                480,
                lambda x, y: ((x + y * 4) % 255, (x * 4 + y) % 255, (x * 2 + y * 2) % 255),
            )
            (project / "generated").mkdir()
            (project / "generated" / "fake_background.png").write_bytes(b"real-background")

            result = bridge.post_build_finalize_provider_project(
                project,
                {"status": "PASS", "example_outputs": {}, "agent_usage": {"events": []}},
                {"copied": {"ui_screenshot": str(screenshot), "background": str(background), "sprite": str(sprite)}},
                session,
                session_dir=session_dir,
                chat_id="chat-vn-post",
            )

            self.assertTrue(result["test_result"]["ok"])
            self.assertTrue(result["image_result"]["ok"])
            self.assertTrue(result["gate"]["delivery_allowed"], result["gate"])
            self.assertEqual("PASS", result["gate"]["canonical_evidence_gate"]["status"])
            self.assertTrue(result["gate"]["canonical_evidence_gate"]["identity_consistent"])
            for field in ("run_id", "candidate_id", "candidate_hash", "commit_sha"):
                self.assertTrue(result["test_result"].get(field), field)
                self.assertEqual(result["test_result"].get(field), result["runtime_result"].get(field), field)
                self.assertEqual(result["test_result"].get(field), result["visual_evidence_result"].get(field), field)
            runtime_result = result["runtime_result"]
            self.assertTrue(runtime_result["execution_root_isolated"], runtime_result)
            self.assertNotEqual(pathlib.Path(runtime_result["cwd"]).resolve(), project.resolve())
            self.assertEqual(runtime_result["source_candidate_hash"], runtime_result["candidate_hash"])
            self.assertEqual(runtime_result["copied_candidate_hash"], runtime_result["candidate_hash"])
            self.assertTrue(runtime_result["cleanup_result"]["removed"])
            self.assertFalse(pathlib.Path(runtime_result["execution_root"]).exists())
            visual_result = result["visual_evidence_result"]
            self.assertEqual(runtime_result["pid"], visual_result["runtime_pid"])
            self.assertEqual(runtime_result["url"], visual_result["runtime_url"])
            self.assertEqual(runtime_result["port"], visual_result["runtime_port"])
            self.assertEqual(runtime_result["execution_root"], visual_result["runtime_execution_root"])
            self.assertEqual(runtime_result["browser_capture_id"], visual_result["browser_capture_id"])
            self.assertEqual(runtime_result["browser_capture_hash"], visual_result["browser_capture_hash"])
            self.assertTrue(visual_result["runtime_alive_before_capture"])
            self.assertTrue(visual_result["runtime_alive_after_capture"])
            self.assertEqual(canonical_evidence_hash.sha256_file(visual_result["screenshot_path"]), visual_result["screenshot_hash"])
            self.assertEqual(
                canonical_evidence_hash.sha256_file(visual_result["customer_runtime_ref"]),
                visual_result["customer_runtime_hash"],
            )
            image_manifest = result["image_result"]["manifest"]
            for item in image_manifest["images"]:
                if item["path"]:
                    self.assertEqual("PASS", item["audit"]["validation"]["status"], item)
                    self.assertTrue(item["audit"]["validation"]["sha256"].startswith("sha256:"), item)
            self.assertTrue(result["gate"]["media_validation"]["validated_assets"])
            rejected_paths = {
                pathlib.Path(item["path"]).name
                for item in result["gate"]["media_validation"]["rejected_assets"]
                if item.get("path")
            }
            self.assertIn("fake_background.png", rejected_paths)
            self.assertEqual(
                "PASS",
                canonical_media_validation.validate_media(
                    result["image_result"]["background"],
                    project,
                    requested_role="background",
                )["status"],
            )
            first_attempt = result["test_result"].get("first_attempt", {})
            if first_attempt:
                self.assertNotEqual(first_attempt.get("candidate_hash"), result["runtime_result"].get("candidate_hash"))
            self.assertTrue((project / "TEST_REPORT.md").exists())
            self.assertIn("exit_code: 0", (project / "TEST_REPORT.md").read_text(encoding="utf-8"))
            self.assertTrue((project / "screenshots" / "provider_ui_screenshot.png").exists())
            self.assertTrue(list((project / "assets" / "generated").glob("background_*.png")))
            self.assertTrue(list((project / "assets" / "generated").glob("sprite_*.png")))
            self.assertTrue((project / "generated_image_manifest.json").exists())
            self.assertTrue((project / "final_project_bundle.zip").exists())

    def test_post_build_finalize_generates_or_blocks_video_honestly(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            project = root / "project"
            project.mkdir()
            (project / "README.md").write_text("# Task Board\n\nRun `python app.py`.\n", encoding="utf-8")
            (project / "app.py").write_text("print('task board')\n", encoding="utf-8")
            (project / "tests").mkdir()
            (project / "tests" / "test_app.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")
            session_dir = root / "sessions"
            session = bridge.default_session("chat-video-blocked")
            session["messages"].append(
                {
                    "role": "user",
                    "text": "做一个任务看板网页应用，必须包含界面截图和30秒以内演示视频",
                    "created_at": bridge.now(),
                }
            )
            session["whiteboard"]["delivery_requirements"] = ["界面截图", "演示视频"]

            result = bridge.post_build_finalize_provider_project(
                project,
                {"status": "PASS", "example_outputs": {}, "agent_usage": {"events": []}},
                {"copied": {}},
                session,
                session_dir=session_dir,
                chat_id="chat-video-blocked",
            )

            self.assertTrue((project / "video_blocked.json").exists())
            self.assertTrue(result["video_result"]["blocked"])
            self.assertFalse(list(project.rglob("*.mp4")))
            self.assertFalse(list(project.rglob("*.webm")))
            self.assertTrue(any("video_blocked" in item for item in result["manifest"]["known_limits"]))

    def test_post_build_finalize_repair_uses_final_candidate_hash(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            project = root / "project"
            (project / "src").mkdir(parents=True)
            (project / "src" / "__init__.py").write_text("", encoding="utf-8")
            (project / "src" / "main.py").write_text("from fastapi import FastAPI\n\napp = FastAPI()\n", encoding="utf-8")
            (project / "index.html").write_text("<main><h1>Repair App</h1></main>\n", encoding="utf-8")
            (project / "README.md").write_text("# Repair App\n", encoding="utf-8")
            (project / "requirements.txt").write_text("pytest\nfastapi>=0.115,<1\nflask>=3,<4\n", encoding="utf-8")
            (project / "tests").mkdir()
            (project / "tests" / "test_repair.py").write_text(
                "from src.main import create_app\n\n"
                "def test_create_app_repair():\n"
                "    assert create_app() is not None\n",
                encoding="utf-8",
            )
            screenshot = project / "runtime_ui_screenshot.png"
            bridge.write_rgb_png(screenshot, 320, 180, lambda x, y: ((x + y) % 255, (x * 2) % 255, (y * 3) % 255))
            session_dir = root / "sessions"
            session = bridge.default_session("chat-repair-post")
            session["messages"].append({"role": "user", "text": "做一个本地网页应用，需要界面截图", "created_at": bridge.now()})

            result = bridge.post_build_finalize_provider_project(
                project,
                {"status": "PASS", "example_outputs": {}, "agent_usage": {"events": []}},
                {"copied": {"ui_screenshot": str(screenshot)}},
                session,
                session_dir=session_dir,
                chat_id="chat-repair-post",
            )

            first_attempt = result["test_result"].get("first_attempt", {})
            self.assertTrue(first_attempt, result["test_result"])
            self.assertNotEqual(first_attempt.get("candidate_hash"), result["test_result"].get("candidate_hash"))
            for field in ("run_id", "candidate_id", "candidate_hash", "commit_sha"):
                self.assertEqual(result["test_result"].get(field), result["runtime_result"].get(field), field)
                self.assertEqual(result["test_result"].get(field), result["visual_evidence_result"].get(field), field)
            self.assertEqual("PASS", result["gate"]["canonical_evidence_gate"]["status"])
            self.assertTrue(result["gate"]["canonical_evidence_gate"]["identity_consistent"])


if __name__ == "__main__":
    unittest.main()
