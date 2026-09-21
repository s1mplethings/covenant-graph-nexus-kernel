from __future__ import annotations

import json
import pathlib
import subprocess

import pytest

from cgkn_agent_kit import core
from cgkn_agent_kit.cli import _emit, main


CGKN_ROOT = pathlib.Path(__file__).resolve().parents[3]


def test_cli_json_output_reconfigures_legacy_windows_stream_to_utf8() -> None:
    class LegacyStream:
        def __init__(self) -> None:
            self.encoding = "cp1252"
            self.errors = "strict"
            self.value = ""

        def reconfigure(self, *, encoding: str, errors: str) -> None:
            self.encoding = encoding
            self.errors = errors

        def write(self, value: str) -> int:
            value.encode(self.encoding, errors=self.errors)
            self.value += value
            return len(value)

        def flush(self) -> None:
            return None

    stream = LegacyStream()
    _emit({"message": "中文路径"}, stream=stream)
    assert stream.encoding == "utf-8"
    assert "中文路径" in stream.value


def initialized(tmp_path: pathlib.Path) -> pathlib.Path:
    project = tmp_path / "sample project"
    project.mkdir()
    core.initialize_project(project, CGKN_ROOT)
    return project


def test_init_is_project_local_and_does_not_store_secrets(tmp_path: pathlib.Path) -> None:
    project = initialized(tmp_path)
    config = json.loads((project / ".cgkn" / "agent-kit.json").read_text(encoding="utf-8"))

    assert config["stores_secrets"] is False
    assert config["provider_entrypoint"] == "scripts/run_codex_conversation_generation.py"
    assert (project / ".cgkn" / "agent-kit" / ".gitignore").read_text(encoding="utf-8") == "*\n!.gitignore\n"
    assert list(project.iterdir()) == [project / ".cgkn"]


def test_scan_is_bounded_and_excludes_secret_and_build_paths(tmp_path: pathlib.Path) -> None:
    project = initialized(tmp_path)
    (project / "README.md").write_text("Project overview", encoding="utf-8")
    fake_secret = "sk-" + ("a" * 20)
    (project / "main.py").write_text(f'API_TOKEN="{fake_secret}"\nprint("ok")', encoding="utf-8")
    (project / ".env").write_text("OPENAI_API_KEY=not-readable", encoding="utf-8")
    (project / "credentials.json").write_text('{"password":"never-read"}', encoding="utf-8")
    (project / "node_modules").mkdir()
    (project / "node_modules" / "library.js").write_text("ignored", encoding="utf-8")

    context = core.scan_project(project, max_items=2)
    serialized = json.dumps(context)

    assert len(context["selected_items"]) == 2
    assert context["selected_items"][0]["path"] == "README.md"
    assert fake_secret not in serialized
    assert "never-read" not in serialized
    assert "[REDACTED]" in serialized
    assert all("node_modules" not in item["path"] for item in context["selected_items"])


def test_prepare_and_manual_seal_use_real_supervisor_contract(tmp_path: pathlib.Path) -> None:
    project = initialized(tmp_path)
    (project / "README.md").write_text("A small inventory CLI", encoding="utf-8")
    request = core.prepare_request(
        project, goal="Build the inventory CLI", gap="Need bounded architecture guidance",
        category="planning_gap",
    )
    draft = project / "draft.json"
    core.write_json(draft, {
        "workflow_state": "ready",
        "summary": "Use a compact domain, repository, service, and CLI design.",
        "diagnosis": ["The interface boundary is not yet explicit."],
        "provider_guidance": ["Give persistence and CLI parsing separate owners."],
        "repair_targets": ["src/main.py"],
        "acceptance_checks": ["Run add, list, update, and delete through the real CLI."],
        "context_requests": [],
        "tool_evidence_requests": ["Run the generated test suite."],
        "known_limits": ["Advisory guidance is not delivery evidence."],
    })

    brief = core.seal_draft(project, request, draft)
    value = core.read_json(brief)

    assert value["kind"] == "CGKNCodexCapabilityBrief"
    assert value["authority"]["candidate_write_authorized"] is False
    assert value["authority"]["formal_evidence_status"] == "NOT_EVALUATED"
    assert (project / ".cgkn" / "agent-kit" / "whiteboard_patch.json").is_file()
    assert len((project / ".cgkn" / "agent-kit" / "agent_session.jsonl").read_text(encoding="utf-8").splitlines()) == 3


def test_codex_invocation_is_ephemeral_read_only_and_schema_constrained(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = initialized(tmp_path)
    request = project / ".cgkn" / "agent-kit" / "request.json"
    core.write_json(request, {"kind": "test-request"})
    captured: dict[str, object] = {}

    def fake_run(argv: list[str], *, cwd: pathlib.Path, input_text: str | None = None, timeout: int = 600):
        captured.update(argv=argv, cwd=cwd, input_text=input_text, timeout=timeout)
        output = pathlib.Path(argv[argv.index("--output-last-message") + 1])
        core.write_json(output, {"workflow_state": "needs_context"})
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

    monkeypatch.setattr(core, "_run", fake_run)
    draft = core.codex_draft(project, request, codex_command="codex-test", timeout=77)
    argv = captured["argv"]

    assert draft.is_file()
    assert argv[:2] == ["codex-test", "exec"]
    assert "--ephemeral" in argv
    assert argv[argv.index("--sandbox") + 1] == "read-only"
    assert "--output-schema" in argv
    assert "danger-full-access" not in argv
    assert captured["cwd"] == project.resolve()


def test_doctor_reports_unusable_codex_without_faking_readiness(tmp_path: pathlib.Path) -> None:
    project = initialized(tmp_path)
    report = core.doctor(project, codex_command=str(tmp_path / "missing-codex.exe"))

    assert report["provider_mainline_available"] is True
    assert report["ready_for_manual_agent"] is True
    assert report["ready_for_codex_automation"] is False
    assert report["codex"]["usable"] is False


def test_project_config_cannot_redirect_support_artifacts_outside_dot_cgkn(tmp_path: pathlib.Path) -> None:
    project = initialized(tmp_path)
    config_path = project / ".cgkn" / "agent-kit.json"
    config = core.read_json(config_path)
    config["artifact_dir"] = "../outside"
    core.write_json(config_path, config)

    with pytest.raises(core.AgentKitError, match="relative path under .cgkn"):
        core.load_project(project)


def test_explicit_wrong_cgkn_root_is_not_silently_replaced(tmp_path: pathlib.Path) -> None:
    with pytest.raises(core.AgentKitError, match="Not a compatible CGKN checkout"):
        core.resolve_cgkn_root(str(tmp_path / "wrong"))


def test_generation_command_has_one_formal_entry_and_no_secret_argument(tmp_path: pathlib.Path) -> None:
    project = initialized(tmp_path)
    brief = project / "brief.json"
    argv = core.generation_command(
        project, goal="Build a useful CLI", brief_path=brief,
        out_dir=project / "generated output", allow_network=True,
    )
    joined = " ".join(argv)

    assert argv[1] == str(CGKN_ROOT / "scripts" / "run_codex_conversation_generation.py")
    assert "--codex-capability-brief" in argv
    assert "--use-api" in argv and "--allow-provider" in argv
    assert "--allow-network" in argv
    assert "--api-key" not in argv
    assert "local_packager.py" not in joined
    assert "run_local_pipeline.py" not in joined


def test_generation_command_routes_every_provider_stage_to_selected_model(tmp_path: pathlib.Path) -> None:
    project = initialized(tmp_path)
    selected_model = "qwen3.8-max"

    argv = core.generation_command(
        project,
        goal="Build a useful CLI",
        brief_path=project / "brief.json",
        model=selected_model,
    )

    assert argv[argv.index("--model") + 1] == selected_model
    assert argv[argv.index("--small-model") + 1] == selected_model
    assert argv[argv.index("--large-model") + 1] == selected_model


def test_generation_command_can_select_the_existing_formal_resume_route(tmp_path: pathlib.Path) -> None:
    project = initialized(tmp_path)
    run_dir = project / ".cgkn" / "agent-kit" / "runs"
    argv = core.generation_command(
        project,
        goal="Resume a useful CLI",
        brief_path=project / "brief.json",
        resume_run_dir=run_dir,
    )

    assert argv[-2:] == ["--resume-run-dir", str(run_dir.resolve())]


def test_cli_dry_run_works_from_path_with_spaces(tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]) -> None:
    project = initialized(tmp_path)
    exit_code = main(["generate", "--project", str(project), "--goal", "Build a CLI", "--dry-run"])
    output = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert output["executed"] is False
    assert output["secrets_in_argv"] is False
    assert str(project.resolve()) in " ".join(output["argv"])
