from __future__ import annotations

import ast
import json
import subprocess
import sys

import pytest

from cgkn.application.project_campaign.matrix import campaign_matrix
from cgkn.application.provider_evaluation import ProjectProviderPlan
from cgkn.application.software_project.greenfield import (
    CLIArgumentAction, CLIArgumentKind, CLIArgumentSpec, CLICommandSpec, CLIDispatchSpec,
    CLIErrorMapping, CLIOutputSpec, DeterministicCLICompiler, StructuredCLIPlan,
)


def _plan(project_id="duplicate_finder_cli"):
    case = next(item for item in campaign_matrix() if item.project_id == project_id)
    return StructuredCLIPlan.from_dict(case.cli_contract)


def test_plan_round_trip_and_hash_stability():
    plan = _plan()
    assert StructuredCLIPlan.from_dict(plan.as_dict()).as_dict() == plan.as_dict()
    assert StructuredCLIPlan.from_dict(plan.as_dict()).plan_hash == plan.plan_hash


@pytest.mark.parametrize("project_id", ["duplicate_finder_cli", "env_audit_cli", "rename_plan_cli", "todo_json_cli"])
def test_explicit_matrix_contracts_compile(project_id):
    source = DeterministicCLICompiler().render_main(_plan(project_id))
    ast.parse(source)
    assert "ProductionGenerationClient" not in source


def test_variadic_positional_is_preserved():
    plan = _plan("ini_merge_cli")
    assert plan.commands[0].positionals[-1].nargs == "+"


def test_subcommands_and_global_option_are_explicit():
    plan = _plan("todo_json_cli")
    assert {item.subcommand_name for item in plan.commands} == {"add", "list", "done", "delete"}
    assert plan.global_options[0].flags == ("--store",)


def test_repeatable_option_contract():
    argument = CLIArgumentSpec("tag", CLIArgumentKind.OPTION, ("--tag",), "tag", repeatable=True, action=CLIArgumentAction.APPEND)
    assert CLIArgumentSpec.from_dict(argument.as_dict()) == argument


def test_repeatable_requires_append():
    with pytest.raises(ValueError, match="REPEATABLE"):
        CLIArgumentSpec("tag", CLIArgumentKind.OPTION, ("--tag",), "tag", repeatable=True)


def test_arbitrary_dispatch_expression_is_rejected():
    with pytest.raises(ValueError, match="ARGUMENT_INVALID"):
        CLIDispatchSpec("x.core", "execute", "x", {"x": "$args.x + 1"})


def test_multi_command_requires_named_subcommands():
    command = CLICommandSpec("x", "", "", (), (), CLIDispatchSpec("x.core", "execute", "x", {}))
    with pytest.raises(ValueError, match="UNSUPPORTED"):
        StructuredCLIPlan("x", "x.__main__", "python -m x", (command, command))


def test_init_exports_are_deterministic():
    compiler = DeterministicCLICompiler()
    first = compiler.render_init(domain_module="sample.core", exports=("run", "ProjectError", "cli_execute"))
    assert first == compiler.render_init(domain_module="sample.core", exports=("run", "ProjectError", "cli_execute"))
    assert "cli_execute" not in first and "run" in first


def test_generated_cli_help_has_no_domain_import_side_effect(tmp_path):
    package = tmp_path / "duplicate_finder"; package.mkdir()
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "core.py").write_text("raise RuntimeError('domain imported during help')\n", encoding="utf-8")
    (package / "__main__.py").write_text(DeterministicCLICompiler().render_main(_plan()), encoding="utf-8")
    result = subprocess.run([sys.executable, "-m", "duplicate_finder", "--help"], cwd=tmp_path, capture_output=True, text=True)
    assert result.returncode == 0 and "usage:" in result.stdout.lower() and not result.stderr


def test_generated_cli_json_and_project_error_mapping(tmp_path):
    package = tmp_path / "env_audit"; package.mkdir()
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "core.py").write_text(
        "class ProjectError(ValueError): pass\n"
        "def execute(operation, parameters):\n"
        "    if parameters['path'] == 'bad': raise ProjectError('controlled')\n"
        "    return {'kind':'json','value':{'file':parameters['path']}}\n", encoding="utf-8")
    (package / "__main__.py").write_text(DeterministicCLICompiler().render_main(_plan("env_audit_cli")), encoding="utf-8")
    ok = subprocess.run([sys.executable, "-m", "env_audit", "good", "--json"], cwd=tmp_path, capture_output=True, text=True)
    bad = subprocess.run([sys.executable, "-m", "env_audit", "bad"], cwd=tmp_path, capture_output=True, text=True)
    assert ok.returncode == 0 and json.loads(ok.stdout) == {"file": "good"}
    assert bad.returncode == 2 and bad.stderr == "controlled\n" and "Traceback" not in bad.stderr


def test_cli_compiler_has_no_provider_imports():
    source = __import__("inspect").getsource(__import__("cgkn.application.software_project.greenfield.cli", fromlist=["x"]))
    for forbidden in ("CompletionClient", "ProviderConnector", "ModelRoleConfig", "ProductionGenerationClient"):
        assert forbidden not in source


def test_project_plan_backup_only_before_candidate():
    plan = ProjectProviderPlan("p", "qwen", "deepseek", "qwen", "grok", "grok", "qwen", {"project.domain.simple": "deepseek"}, {}, {}, {})
    assert plan.authorize_backup("project.domain.simple", failure_domain="PROVIDER_TRANSPORT_FAILURE", action="RETRY_WITH_PRESELECTED_BACKUP") == "deepseek"
    with pytest.raises(RuntimeError, match="ROUTE_AUTHORITY"):
        plan.authorize_backup("project.domain.simple", failure_domain="PROVIDER_TRANSPORT_FAILURE", candidate_revision_id="r1", action="RETRY_WITH_PRESELECTED_BACKUP")
